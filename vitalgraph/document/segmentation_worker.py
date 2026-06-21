"""
Segmentation Background Worker.

Polls the segmentation_jobs table and processes pending jobs. Designed to
run as a long-lived asyncio.Task started at application boot.

Usage:
    worker = SegmentationWorker(space_manager)
    task = asyncio.create_task(worker.run())

    # To stop gracefully:
    worker.stop()
    await task
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from vitalgraph.document.segmentation_job_manager import (
    SegmentationJobDTO,
    SegmentationJobManager,
)

logger = logging.getLogger(__name__)

# Safety-net poll interval when LISTEN is active (seconds).
# The worker wakes instantly on NOTIFY; this is only a fallback.
_IDLE_POLL_INTERVAL = 30.0
# Short delay between consecutive jobs
_BUSY_POLL_INTERVAL = 0.2
# Max concurrent segmentation tasks
_MAX_CONCURRENT = 4


class SegmentationWorker:
    """
    Background worker that claims and processes segmentation jobs.

    Uses SELECT ... FOR UPDATE SKIP LOCKED via SegmentationJobManager
    to safely dequeue jobs across concurrent workers.
    """

    def __init__(self, space_manager):
        """
        Args:
            space_manager: VitalGraph space manager for DB access.
        """
        self._space_manager = space_manager
        self._running = False
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        self._wake_event = asyncio.Event()
        self._listen_conns: list = []  # dedicated LISTEN connections

    def stop(self) -> None:
        """Signal the worker to stop after the current poll cycle."""
        self._running = False
        self._wake_event.set()  # unblock wait_for immediately

    async def run(self) -> None:
        """
        Main worker loop. Polls all active spaces for pending jobs.

        Uses PostgreSQL LISTEN/NOTIFY for instant wake when jobs are
        enqueued. Falls back to a safety-net poll interval.
        """
        self._running = True
        logger.info("Segmentation worker started")

        await self._setup_listeners()

        while self._running:
            try:
                did_work = await self._poll_all_spaces()
                interval = _BUSY_POLL_INTERVAL if did_work else _IDLE_POLL_INTERVAL
            except Exception as e:
                logger.error(f"Worker poll error: {e}", exc_info=True)
                interval = _IDLE_POLL_INTERVAL

            # Wait for NOTIFY wake or safety-net timeout
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=interval)
                logger.info("Worker woken by NOTIFY")
            except asyncio.TimeoutError:
                logger.info("Worker safety-net poll (timeout=%.1fs)", interval)

        await self._teardown_listeners()
        logger.info("Segmentation worker stopped")

    # ------------------------------------------------------------------
    # LISTEN / NOTIFY helpers
    # ------------------------------------------------------------------

    async def _setup_listeners(self) -> None:
        """Set up LISTEN on each active space's notification channel."""
        space_ids = self._get_active_space_ids()
        for space_id in space_ids:
            try:
                conn = await self._get_listen_connection(space_id)
                if conn is None:
                    continue
                channel = f"{space_id}_seg_jobs"
                await conn.add_listener(channel, self._on_notify)
                self._listen_conns.append((conn, channel))
                logger.info("LISTEN on channel %s", channel)
            except Exception as e:
                logger.warning("Could not set up LISTEN for %s: %s", space_id, e)

    async def _teardown_listeners(self) -> None:
        """Remove listeners and close dedicated connections."""
        for conn, channel in self._listen_conns:
            try:
                await conn.remove_listener(channel, self._on_notify)
            except Exception:
                pass
            try:
                await conn.close()
            except Exception:
                pass
        self._listen_conns.clear()

    def _on_notify(self, conn, pid, channel, payload) -> None:
        """asyncpg notification callback — sets the wake event."""
        logger.debug("NOTIFY received on %s: %s", channel, payload)
        self._wake_event.set()

    async def _get_listen_connection(self, space_id: str):
        """Acquire a *dedicated* raw asyncpg connection for LISTEN.

        LISTEN requires a long-lived connection that is NOT returned to
        the pool, so we create a standalone one.
        """
        try:
            space_record = await self._space_manager.get_space_or_load(space_id)
            if not space_record:
                return None
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return None
            pool = getattr(backend_impl, '_pool', None)
            if pool is None:
                pool = getattr(backend_impl, '_db', None)
                if pool:
                    pool = getattr(pool, '_pool', None)
            if pool is None:
                return None
            # asyncpg pool exposes the DSN; create a standalone connection
            import asyncpg
            dsn = pool.get_connect_kwargs() if hasattr(pool, 'get_connect_kwargs') else None
            if dsn is None and hasattr(pool, '_connect_kwargs'):
                dsn = pool._connect_kwargs
            if dsn and isinstance(dsn, dict):
                conn = await asyncpg.connect(**dsn)
                return conn
            # Fallback: use pool.acquire (less ideal but functional)
            return None
        except Exception as e:
            logger.warning("Could not create LISTEN connection for %s: %s", space_id, e)
            return None

    async def _poll_all_spaces(self) -> bool:
        """Poll each active space for pending jobs. Returns True if any work was done."""
        if not self._space_manager:
            return False

        space_ids = self._get_active_space_ids()
        if not space_ids:
            return False

        logger.info("Polling %d space(s) for segmentation jobs", len(space_ids))
        did_work = False

        for space_id in space_ids:
            try:
                processed = await self._poll_space(space_id)
                if processed:
                    did_work = True
            except Exception as e:
                logger.error(f"Error polling space {space_id}: {e}", exc_info=True)

        return did_work

    async def _poll_space(self, space_id: str) -> bool:
        """Try to claim and process one job for a space. Returns True if a job was processed."""
        pool = await self._get_pool(space_id)
        if not pool:
            logger.warning("No pool for space %s, skipping", space_id)
            return False

        async with pool.acquire() as conn:
            try:
                manager = SegmentationJobManager(conn, space_id)
                await manager.ensure_table()

                job = await manager.claim_next()
                if not job:
                    return False

                # Process under semaphore to bound concurrency
                async with self._semaphore:
                    await self._process_job(space_id, job, manager)
                return True
            except Exception as e:
                logger.error(f"Error in poll_space({space_id}): {e}", exc_info=True)
                return False

    async def _process_job(
        self,
        space_id: str,
        job: SegmentationJobDTO,
        manager: SegmentationJobManager,
    ) -> None:
        """Process a single segmentation job."""
        logger.info(f"Processing job {job.job_id}: {job.document_uri} (attempt {job.attempt_count})")

        try:
            # Get backend for the space
            space_record = await self._space_manager.get_space_or_load(space_id)
            if not space_record:
                await manager.fail(job.job_id, f"Space {space_id} not available")
                return

            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                await manager.fail(job.job_id, "Backend not available")
                return

            # Fetch document properties
            doc_properties = await self._fetch_document_properties(
                backend_impl, space_id, job.graph_id, job.document_uri
            )
            if doc_properties is None:
                await manager.fail(job.job_id, f"Document {job.document_uri} not found")
                return

            # Build segmentation config
            config = self._build_config(job.segment_method_uri, job.max_segment_tokens)

            # Compute content hash for skip-if-unchanged on future runs
            content_hash = SegmentationJobManager.compute_content_hash(doc_properties)

            # Acquire per-document advisory lock (cross-instance safe)
            lock_manager = getattr(
                getattr(space_impl, 'backend', None),
                'entity_lock_manager', None,
            )
            if lock_manager:
                async with lock_manager.lock(job.document_uri):
                    segment_count = await self._execute_segmentation(
                        backend_impl, space_impl, space_id, job.graph_id,
                        job.document_uri, doc_properties, config,
                    )
            else:
                segment_count = await self._execute_segmentation(
                    backend_impl, space_impl, space_id, job.graph_id,
                    job.document_uri, doc_properties, config,
                )

            await manager.complete(job.job_id, segment_count, content_hash=content_hash)

        except TimeoutError as te:
            logger.warning(f"Job {job.job_id} lock timeout: {te}")
            try:
                await manager.fail(job.job_id, f"Lock timeout: {te}")
            except Exception as fail_err:
                logger.error(f"Could not mark job {job.job_id} as failed: {fail_err}")
        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}", exc_info=True)
            try:
                await manager.fail(job.job_id, str(e)[:2000])
            except Exception as fail_err:
                logger.error(f"Could not mark job {job.job_id} as failed: {fail_err}")

    async def _execute_segmentation(
        self,
        backend_impl,
        space_impl,
        space_id: str,
        graph_id: str,
        document_uri: str,
        doc_properties: dict,
        config,
    ) -> int:
        """Run the segmentation pipeline. Returns segment count."""
        from vitalgraph.document import KGDocumentSegmentationProcessor

        tokenizer = self._get_tokenizer()
        processor = KGDocumentSegmentationProcessor(tokenizer=tokenizer)

        output = processor.process(
            original_uri=document_uri,
            original_properties=doc_properties,
            config=config,
        )

        # Delete existing segmentation for this method
        await self._delete_existing_segmentation(
            backend_impl, space_id, graph_id,
            document_uri, output.method_uri,
        )

        # Store parent copy + segments + edges
        await self._store_segmentation_output(
            backend_impl, space_id, graph_id, output,
        )

        # Schedule vectorization if auto_sync available
        self._schedule_vectorization(space_impl, space_id, graph_id, output)

        logger.info(
            f"Segmented {document_uri}: {output.segment_count} segments "
            f"(method={output.method_uri})"
        )
        return output.segment_count

    # ------------------------------------------------------------------
    # Helpers (largely mirrored from KGDocumentsEndpoint)
    # ------------------------------------------------------------------

    def _get_active_space_ids(self):
        """Get list of currently active space IDs."""
        try:
            if hasattr(self._space_manager, 'get_active_space_ids'):
                return self._space_manager.get_active_space_ids()
            if hasattr(self._space_manager, '_spaces'):
                return list(self._space_manager._spaces.keys())
        except Exception as e:
            logger.warning(f"Could not get active space IDs: {e}")
        return []

    async def _get_pool(self, space_id: str):
        """Get the asyncpg pool for a space."""
        try:
            space_record = await self._space_manager.get_space_or_load(space_id)
            if not space_record:
                return None
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return None
            # Direct connection_pool on backend (SparqlSQLDbImpl)
            if hasattr(backend_impl, 'connection_pool') and backend_impl.connection_pool:
                return backend_impl.connection_pool
            # SparqlSQLSpaceImpl has db_impl -> connection_pool
            db_impl = getattr(backend_impl, 'db_impl', None)
            if db_impl:
                pool = getattr(db_impl, 'connection_pool', None)
                if pool:
                    return pool
            # _pool property (may raise RuntimeError if not connected)
            if hasattr(backend_impl, '_pool'):
                try:
                    return backend_impl._pool
                except RuntimeError:
                    pass
            # _db._pool (SparqlSQLSpaceImpl._db._pool pattern)
            _db = getattr(backend_impl, '_db', None)
            if _db:
                pool = getattr(_db, 'connection_pool', None) or getattr(_db, '_pool', None)
                if pool:
                    return pool
        except Exception as e:
            logger.error(f"Error getting pool for space {space_id}: {e}")
        return None

    async def _get_connection(self, space_id: str):
        """Get a DB connection for a space (caller must release)."""
        pool = await self._get_pool(space_id)
        if pool:
            return await pool.acquire()
        return None

    async def _fetch_document_properties(
        self, backend_impl, space_id: str, graph_id: str, document_uri: str
    ) -> Optional[dict]:
        """Fetch document properties from the backend using SPARQL."""
        try:
            sparql = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>

                SELECT ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        <{document_uri}> ?p ?o .
                    }}
                }}
            """
            result = await backend_impl.execute_sparql_query(space_id, sparql)
            bindings = result.get('results', {}).get('bindings', [])
            if not bindings:
                return None

            # Convert to property dict
            props = {"URI": document_uri}
            for row in bindings:
                pred = row.get("p", {}).get("value", "")
                obj_val = row.get("o", {}).get("value", "")

                if "hasKGDocumentContent" in pred:
                    props["kGDocumentContent"] = str(obj_val)
                elif "hasKGDocumentExtractedContent" in pred:
                    props["kGDocumentExtractedContent"] = str(obj_val)
                elif "hasKGDocumentHTMLContent" in pred:
                    props["kGDocumentHTMLContent"] = str(obj_val)
                elif "hasKGDocumentHeadline" in pred:
                    props["kGDocumentHeadline"] = str(obj_val)
                elif "hasKGDocumentSummary" in pred:
                    props["kGDocumentSummary"] = str(obj_val)
                elif "hasKGDocumentURL" in pred:
                    props["kGDocumentURL"] = str(obj_val)
                elif "hasKGDocumentType" in pred:
                    props["kGDocumentType"] = str(obj_val)
                elif "hasPrimaryLanguageType" in pred:
                    props["primaryLanguageType"] = str(obj_val)
                elif "hasKGGraphURI" in pred or "kGGraphURI" in pred:
                    props["kGGraphURI"] = str(obj_val)
                elif "hasName" in pred:
                    props["name"] = str(obj_val)

            if len(props) > 1:
                content = props.get("kGDocumentContent", "")
                logger.info("Fetched doc %s: %d props, content length=%d, first 100=%r",
                            document_uri, len(props), len(content), content[:100])
                return props
            return None
        except Exception as e:
            logger.error(f"Error fetching properties for {document_uri}: {e}")
            return None

    def _build_config(self, method_uri: Optional[str], max_tokens: Optional[int]):
        """Build segmentation config from job parameters."""
        from vitalgraph.document import MarkdownSegmentConfig, PlainSplitConfig

        kwargs = {}
        if max_tokens:
            kwargs["max_segment_tokens"] = max_tokens
        kwargs["min_segment_tokens"] = 20

        if method_uri == "urn:segmethod:plain_recursive_split":
            return PlainSplitConfig(**kwargs)
        elif method_uri == "urn:segmethod:markdown_heading_split":
            return MarkdownSegmentConfig(**kwargs)
        else:
            return None  # Auto-detect

    def _get_tokenizer(self):
        """Get tokenizer from vector provider if available."""
        try:
            from vitalgraph.vectorization import get_provider
            provider = get_provider("vitalsigns")
            if provider and hasattr(provider, "_tokenizer"):
                return provider._tokenizer
        except Exception:
            pass
        return None

    async def _delete_existing_segmentation(
        self, backend_impl, space_id: str, graph_id: str,
        original_uri: str, method_uri: str,
    ) -> None:
        """Delete existing segmentation by traversing edges from the original document.

        Finds parent copies and segments by following Edge_hasKGDocumentSegment
        relationships, then deletes all discovered URIs (edges, parent, segments).
        Never assumes URI structure — uses graph traversal only.
        """
        try:
            # Step 1: Find edges FROM the original document to parent copies
            # Filter by method_uri to only delete segmentation for this method
            sparql_edges_from_original = f"""
                SELECT ?edge ?parent WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{original_uri}> .
                        ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?parent .
                        ?parent <http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentMethodURI> "{method_uri}" .
                    }}
                }}
            """
            result = await backend_impl.execute_sparql_query(space_id, sparql_edges_from_original)
            bindings = result.get('results', {}).get('bindings', [])
            if not bindings:
                return  # No existing segmentation to delete

            uris_to_delete = []
            parent_uris = []

            for row in bindings:
                edge_uri = row.get("edge", {}).get("value", "")
                parent_uri = row.get("parent", {}).get("value", "")
                if edge_uri:
                    uris_to_delete.append(edge_uri)
                if parent_uri:
                    uris_to_delete.append(parent_uri)
                    parent_uris.append(parent_uri)

            # Step 2: For each parent, find edges to segments and the segments themselves
            for parent_uri in parent_uris:
                sparql_segments = f"""
                    SELECT ?edge ?seg WHERE {{
                        GRAPH <{graph_id}> {{
                            ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{parent_uri}> .
                            ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?seg .
                        }}
                    }}
                """
                seg_result = await backend_impl.execute_sparql_query(space_id, sparql_segments)
                seg_bindings = seg_result.get('results', {}).get('bindings', [])
                for row in seg_bindings:
                    edge_uri = row.get("edge", {}).get("value", "")
                    seg_uri = row.get("seg", {}).get("value", "")
                    if edge_uri:
                        uris_to_delete.append(edge_uri)
                    if seg_uri:
                        uris_to_delete.append(seg_uri)

            if uris_to_delete:
                await backend_impl.db_ops.remove_quads_by_subject_uris(
                    space_id, uris_to_delete, graph_id=graph_id
                )
                logger.info("Deleted %d objects for existing segmentation of %s",
                            len(uris_to_delete), original_uri)
        except Exception as e:
            logger.warning(f"Error deleting existing segmentation: {e}")

    async def _store_segmentation_output(
        self, backend_impl, space_id: str, graph_id: str, output,
    ) -> None:
        """Store the segmentation output as quads."""
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

            # Convert to quads and store
            graph_uri_ref = URIRef(graph_id)
            if len(vs_objects) == 1:
                triples = vs_objects[0].to_triples()
            else:
                triples = vs_objects[0].to_triples_list(vs_objects)

            quads = [(s, p, o, graph_uri_ref) for s, p, o in triples]
            await backend_impl.add_rdf_quads_batch_bulk(space_id, quads)
            logger.info(f"Stored {len(quads)} quads for segmentation output")

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

    def _schedule_vectorization(
        self, space_impl, space_id: str, graph_id: str, output,
    ) -> None:
        """Schedule vectorization for the segmentation output."""
        try:
            backend_impl = getattr(space_impl, 'backend', None)
            db_impl = getattr(backend_impl, 'db_impl', None) if backend_impl else None
            if not db_impl:
                return

            from vitalgraph.vectorization.auto_sync import schedule_sync
            uris = [output.parent_copy_properties["URI"]]
            for seg in output.segment_properties_list:
                uris.append(seg["URI"])
            schedule_sync(
                db_impl=db_impl,
                space_id=space_id,
                subject_uris=uris,
                graph_uri=graph_id,
                operation="upsert",
            )
            logger.info(f"Triggered vectorization for {len(uris)} subjects")
        except Exception as e:
            logger.warning(f"Could not trigger vectorization: {e}")
