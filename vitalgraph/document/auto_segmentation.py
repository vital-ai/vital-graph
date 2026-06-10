"""
Auto-Segmentation Hook.

Called after KGDocument insert/update to check whether the document's
kGDocumentType matches a registered segmentation config. If so,
triggers segmentation automatically.

Usage:
    hook = AutoSegmentationHook(space_id, backend_impl, conn)
    await hook.on_document_upsert(document_uri, document_properties, graph_id)
"""

import logging
from typing import Callable, Optional

from vitalgraph.document.kgdocument_segmentation_processor import (
    KGDocumentSegmentationProcessor,
    extract_content,
)
from vitalgraph.document.segment_config import MarkdownSegmentConfig, PlainSplitConfig
from vitalgraph.document.segmentation_config_manager import (
    SegmentationConfigDTO,
    SegmentationConfigManager,
)

logger = logging.getLogger(__name__)


class AutoSegmentationHook:
    """
    Hook that triggers auto-segmentation when a KGDocument is created or updated
    and its kGDocumentType matches a registered segmentation config.

    Designed to be called from the document CRUD endpoint after successful storage.
    """

    def __init__(self, space_id: str, backend_impl, conn, tokenizer: Optional[Callable[[str], int]] = None):
        """
        Args:
            space_id: Space identifier.
            backend_impl: Backend implementation for quad store operations.
            conn: asyncpg connection for config table access.
            tokenizer: Optional token counting function (matches vector provider).
        """
        self._space_id = space_id
        self._backend = backend_impl
        self._conn = conn
        self._tokenizer = tokenizer
        self._config_manager = SegmentationConfigManager(conn, space_id)

    async def on_document_upsert(
        self,
        document_uri: str,
        document_properties: dict,
        graph_id: str,
        lock_manager=None,
    ) -> bool:
        """
        Check if document matches any auto-segmentation config and trigger if so.

        Args:
            document_uri: URI of the KGDocument that was inserted/updated.
            document_properties: Properties dict of the document (short TS names).
            graph_id: RDF graph ID where the document lives.
            lock_manager: Optional EntityLockManager for advisory locking.

        Returns:
            True if segmentation was triggered, False otherwise.
        """
        doc_type = document_properties.get("kGDocumentType")
        if not doc_type:
            logger.debug(f"No kGDocumentType on {document_uri}, skipping auto-segmentation")
            return False

        # Check if this is already a segment (don't re-segment segments)
        seg_index = document_properties.get("kGDocumentSegmentIndex")
        if seg_index is not None and seg_index > 0:
            return False

        # Also skip if it's a segmentation parent
        seg_type = document_properties.get("kGDocumentSegmentTypeURI", "")
        if seg_type == "urn:segtype:segmentation_parent":
            return False

        # Ensure config table exists
        await self._config_manager.ensure_table()

        # Look up configs for this document type
        configs = await self._config_manager.get_config_for_document_type(doc_type)
        if not configs:
            logger.debug(f"No auto-segmentation config for type {doc_type}")
            return False

        # Check document has content worth segmenting
        content = extract_content(document_properties)
        if not content:
            logger.debug(f"No content in {document_uri}, skipping auto-segmentation")
            return False

        # Trigger segmentation for each matching config
        triggered = False
        for config_dto in configs:
            try:
                success = await self._run_segmentation(
                    document_uri, document_properties, graph_id, config_dto, lock_manager
                )
                if success:
                    triggered = True
                    logger.info(
                        f"Auto-segmented {document_uri} with method={config_dto.segment_method_uri}"
                    )
            except Exception as e:
                logger.error(
                    f"Auto-segmentation failed for {document_uri} "
                    f"method={config_dto.segment_method_uri}: {e}"
                )

        return triggered

    async def _run_segmentation(
        self,
        document_uri: str,
        document_properties: dict,
        graph_id: str,
        config_dto: SegmentationConfigDTO,
        lock_manager=None,
    ) -> bool:
        """Run segmentation for a single config."""
        # Build config from DTO
        config = self._dto_to_config(config_dto)

        processor = KGDocumentSegmentationProcessor(tokenizer=self._tokenizer)

        kg_graph_uri = document_properties.get("kGGraphURI", document_uri)

        # Execute under advisory lock if available
        async def _do_segment():
            output = processor.process(
                original_uri=document_uri,
                original_properties=document_properties,
                config=config,
                kg_graph_uri=kg_graph_uri,
            )

            # Delete existing segmentation for this method
            await self._delete_existing(graph_id, document_uri, output.method_uri)

            # Store new segmentation
            await self._store_output(graph_id, output)

            # Trigger vectorization if configured
            if config_dto.auto_vectorize:
                await self._trigger_vectorization(
                    graph_id, output.parent_copy_properties,
                    output.segment_properties_list
                )

            return True

        if lock_manager:
            async with lock_manager.lock(document_uri):
                return await _do_segment()
        else:
            return await _do_segment()

    @staticmethod
    def _dto_to_config(dto: SegmentationConfigDTO):
        """Convert a config DTO to a segmentation config object."""
        if dto.segment_method_uri == "urn:segmethod:plain_recursive_split":
            return PlainSplitConfig(
                max_segment_tokens=dto.max_segment_tokens,
                min_segment_tokens=dto.min_segment_tokens,
                overlap_tokens=dto.overlap_tokens,
            )
        else:
            # Default to markdown
            return MarkdownSegmentConfig(
                max_segment_tokens=dto.max_segment_tokens,
                min_segment_tokens=dto.min_segment_tokens,
                overlap_tokens=dto.overlap_tokens,
            )

    async def _delete_existing(self, graph_id: str, original_uri: str, method_uri: str):
        """Delete existing parent copy + segments for a method."""
        method_suffix = method_uri.split(":")[-1] if ":" in method_uri else "segmented"
        parent_uri = f"{original_uri}_parent_{method_suffix}"

        try:
            # Delete subjects starting with parent URI
            sparql = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        ?s ?p ?o .
                        FILTER(STRSTARTS(STR(?s), "{parent_uri}"))
                    }}
                }}
            """
            await self._backend.execute_sparql_update(self._space_id, sparql)

            # Delete edge from original to parent
            edge_uri = f"{original_uri}_edge_to_{method_suffix}_parent"
            sparql_edge = f"""
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        <{edge_uri}> ?p ?o .
                    }}
                }}
            """
            await self._backend.execute_sparql_update(self._space_id, sparql_edge)
        except Exception as e:
            logger.warning(f"Error deleting existing segmentation: {e}")

    async def _store_output(self, graph_id: str, output):
        """Store segmentation output as quads."""
        try:
            from ai_haley_kg_domain.model.KGDocument import KGDocument
            from ai_haley_kg_domain.model.Edge_hasKGDocumentSegment import Edge_hasKGDocumentSegment
            from rdflib import URIRef

            vs_objects = []

            # Parent copy
            parent = KGDocument()
            self._apply_props(parent, output.parent_copy_properties)
            vs_objects.append(parent)

            # Segments
            for seg_props in output.segment_properties_list:
                seg = KGDocument()
                self._apply_props(seg, seg_props)
                vs_objects.append(seg)

            # Edge: original → parent
            edge_op = Edge_hasKGDocumentSegment()
            edge_op.URI = output.edge_original_to_parent["URI"]
            edge_op.edgeSource = output.edge_original_to_parent["edgeSource"]
            edge_op.edgeDestination = output.edge_original_to_parent["edgeDestination"]
            if output.edge_original_to_parent.get("kGGraphURI"):
                edge_op.kGGraphURI = output.edge_original_to_parent["kGGraphURI"]
            vs_objects.append(edge_op)

            # Edges: parent → segments
            for edge_props in output.edge_parent_to_segments:
                edge = Edge_hasKGDocumentSegment()
                edge.URI = edge_props["URI"]
                edge.edgeSource = edge_props["edgeSource"]
                edge.edgeDestination = edge_props["edgeDestination"]
                if edge_props.get("kGGraphURI"):
                    edge.kGGraphURI = edge_props["kGGraphURI"]
                vs_objects.append(edge)

            # Convert to quads
            graph_uri_ref = URIRef(graph_id)
            if len(vs_objects) == 1:
                triples = vs_objects[0].to_triples()
            else:
                triples = vs_objects[0].to_triples_list(vs_objects)

            quads = [(s, p, o, graph_uri_ref) for s, p, o in triples]
            await self._backend.store_quads(self._space_id, quads)
            logger.info(f"Stored {len(quads)} quads for auto-segmentation")

        except Exception as e:
            logger.error(f"Error storing segmentation output: {e}")
            raise

    @staticmethod
    def _apply_props(obj, props: dict):
        """Apply property dict to a VitalSigns KGDocument object."""
        obj.URI = props.get("URI", "")
        if props.get("name"):
            obj.name = props["name"]
        if props.get("kGDocumentContent"):
            obj.kGDocumentContent = props["kGDocumentContent"]
        if props.get("kGraphDescription"):
            obj.kGraphDescription = props["kGraphDescription"]
        if props.get("kGDocumentType"):
            obj.kGDocumentType = props["kGDocumentType"]
        if props.get("kGDocumentSegmentMethodURI"):
            obj.kGDocumentSegmentMethodURI = props["kGDocumentSegmentMethodURI"]
        if props.get("kGDocumentSegmentTypeURI"):
            obj.kGDocumentSegmentTypeURI = props["kGDocumentSegmentTypeURI"]
        if props.get("kGDocumentSegmentIndex") is not None:
            obj.kGDocumentSegmentIndex = props["kGDocumentSegmentIndex"]
        if props.get("kGDocumentSegmentTokenLength"):
            obj.kGDocumentSegmentTokenLength = props["kGDocumentSegmentTokenLength"]
        if props.get("kGDocumentHeadline"):
            obj.kGDocumentHeadline = props["kGDocumentHeadline"]
        if props.get("kGDocumentURL"):
            obj.kGDocumentURL = props["kGDocumentURL"]
        if props.get("primaryLanguageType"):
            obj.primaryLanguageType = props["primaryLanguageType"]
        if props.get("kGGraphURI"):
            obj.kGGraphURI = props["kGGraphURI"]

    async def _trigger_vectorization(self, graph_id: str, parent_props: dict, segment_props_list: list):
        """Schedule vectorization for parent + segments (async, non-blocking)."""
        try:
            auto_sync = getattr(self._backend, "auto_sync", None)
            if auto_sync is None:
                logger.debug("No auto_sync available, skipping vectorization trigger")
                return

            uris = [parent_props["URI"]]
            for seg in segment_props_list:
                uris.append(seg["URI"])

            # Schedule via auto_sync (fire-and-forget)
            await auto_sync.sync_subjects(self._space_id, graph_id, uris)
            logger.info(f"Triggered vectorization for {len(uris)} subjects")

        except Exception as e:
            logger.warning(f"Could not trigger vectorization: {e}")
