"""
Load DAWG test .ttl data into PostgreSQL space tables.

Parses Turtle files with pyoxigraph, generates deterministic term UUIDs
(matching the vitalgraph convention), and bulk-loads via INSERT.

All functions are async and accept an asyncpg connection.
For DAWG datasets (~4-50 triples) this completes in milliseconds.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pyoxigraph

logger = logging.getLogger(__name__)

# Deterministic UUID generation — matches vitalgraph convention
_VITALGRAPH_NS = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

DEFAULT_GRAPH_URI = "urn:x-dawg-test:default-graph"


def generate_term_uuid(
    term_text: str,
    term_type: str,
    lang: Optional[str] = None,
    datatype: Optional[str] = None,
) -> str:
    """Return a deterministic UUID-5 string for an RDF term."""
    components: list[str] = [term_text, term_type]
    if lang is not None:
        components.append(f"lang:{lang}")
    if datatype is not None:
        components.append(f"dt:{datatype}")
    return str(uuid_mod.uuid5(_VITALGRAPH_NS, "\x00".join(components)))


async def load_ttl_into_space(
    conn,
    ttl_file: Path,
    space_id: str,
    graph_uri: str = DEFAULT_GRAPH_URI,
) -> int:
    """Load a .ttl file into the PostgreSQL space tables.

    Args:
        conn: asyncpg connection.
        ttl_file: Path to Turtle data file.
        space_id: Table prefix (e.g., "dawg_test").
        graph_uri: URI for the default graph context.

    Returns:
        Number of quads loaded.
    """
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"

    # Parse triples with pyoxigraph (detect format from extension)
    ext = ttl_file.suffix.lower()
    mime = {".rdf": "application/rdf+xml", ".nt": "application/n-triples",
            ".nq": "application/n-quads"}.get(ext, "text/turtle")
    triples = []
    try:
        with open(ttl_file, "rb") as f:
            for triple in pyoxigraph.parse(f, mime, base_iri=f"file://{ttl_file}"):
                triples.append(triple)
    except Exception as e:
        logger.error("Failed to parse %s: %s", ttl_file, e)
        return 0

    if not triples:
        logger.debug("No triples in %s", ttl_file)
        return 0

    # Blank node labels are scoped to the document they appear in. pyoxigraph
    # hands back the document-local label verbatim (`_:x`), and term_uuid is
    # uuid5(text, type), so without scoping every `_:x` in the space is ONE
    # node -- two files each saying `_:x` are silently merged. The corpus tests
    # this directly: dataset-09b/-10b join across `data-g3.ttl` and its
    # byte-identical `-dup`, which must yield nothing (issues/131).
    #
    # `skolem_label` is the mechanism already used by the file-import and REST
    # batch paths (issues/076). Deriving the scope from the file's identity
    # rather than randomly keeps re-loading the same document idempotent, which
    # this loader relies on -- it caches by data-file path and reloads.
    from vitalgraph.db.sparql_sql.term_normalize import skolem_label
    bnode_scope = f"file://{ttl_file}"

    # Collect unique terms: key = (text, type, lang, datatype)
    terms: Dict[Tuple[str, str, Optional[str], Optional[str]], str] = {}

    def ensure(text: str, ttype: str, lang: Optional[str] = None,
               datatype: Optional[str] = None) -> str:
        key = (text, ttype, lang, datatype)
        uid = terms.get(key)
        if uid is None:
            uid = generate_term_uuid(text, ttype, lang=lang, datatype=datatype)
            terms[key] = uid
        return uid

    # Register graph URI
    graph_uuid = ensure(graph_uri, "U")

    # Collect terms from triples
    quad_rows: List[Tuple[str, str, str, str]] = []

    for triple in triples:
        # Subject
        s_cls = type(triple.subject).__name__
        if s_cls == "BlankNode":
            s_uuid = ensure(skolem_label(bnode_scope, triple.subject.value), "B")
        else:
            s_uuid = ensure(triple.subject.value, "U")

        # Predicate (always URI)
        p_uuid = ensure(triple.predicate.value, "U")

        # Object
        obj = triple.object
        obj_cls = type(obj).__name__
        if obj_cls == "Literal":
            lang = str(obj.language) if obj.language else None
            # Extract datatype URI; skip xsd:string (default for untyped literals)
            dt = None
            if obj.datatype:
                dt_uri = obj.datatype.value
                if dt_uri != "http://www.w3.org/2001/XMLSchema#string" and \
                   dt_uri != "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString":
                    dt = dt_uri
            o_uuid = ensure(obj.value, "L", lang, datatype=dt)
        elif obj_cls == "BlankNode":
            o_uuid = ensure(skolem_label(bnode_scope, obj.value), "B")
        else:
            o_uuid = ensure(obj.value, "U")

        quad_rows.append((s_uuid, p_uuid, o_uuid, graph_uuid))

    # Load datatype URI → ID mapping from the datatype lookup table
    datatype_table = f"{space_id}_datatype"
    dt_uri_to_id: Dict[str, int] = {}
    rows = await conn.fetch(f"SELECT datatype_uri, datatype_id FROM {datatype_table}")
    for row in rows:
        dt_uri_to_id[row["datatype_uri"]] = row["datatype_id"]

    # Register datatypes this table has never seen.
    #
    # The table ships seeded with 38 well-known XSD/RDF datatypes, and this
    # loader used to do a bare `.get(datatype)` against it — so a USER-DEFINED
    # datatype IRI silently became NULL and the literal came back untyped.
    # Found 2026-08-16 via csv-tsv-res/tsv03, whose data carries
    # `"5,5"^^<http://example.org/myCustomDatatype>`.
    #
    # This was a defect in the HARNESS, not the backend: the production ingest
    # paths (`sparql_sql_space_impl._resolve_all_datatypes` and
    # `emit_update._datatype_id`) both INSERT an unseen datatype URI and use the
    # returned id. So the conformance suite was loading data through a path that
    # loses information production preserves — which would have reported a
    # backend defect that does not exist, and would equally have hidden a real
    # one by making every custom-datatype literal untyped on both sides.
    unknown = {
        datatype
        for (_text, _ttype, _lang, datatype) in terms
        if datatype and datatype not in dt_uri_to_id
    }
    for uri in sorted(unknown):
        dt_uri_to_id[uri] = await conn.fetchval(
            f"INSERT INTO {datatype_table} (datatype_uri) VALUES ($1) "
            f"ON CONFLICT (datatype_uri) DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
            f"RETURNING datatype_id",
            uri,
        )

    # Bulk insert terms (asyncpg executemany with $1..$5 params)
    term_rows = [
        (uuid_mod.UUID(uid), text, ttype, lang,
         dt_uri_to_id.get(datatype) if datatype else None)
        for (text, ttype, lang, datatype), uid in terms.items()
    ]
    await conn.executemany(
        f"INSERT INTO {term_table} (term_uuid, term_text, term_type, lang, datatype_id, dataset) "
        f"VALUES ($1, $2, $3, $4, $5, 'primary') "
        f"ON CONFLICT (term_uuid) DO NOTHING",
        term_rows,
    )

    # Bulk insert quads (asyncpg executemany with $1..$4 params)
    quad_rows_uuid = [
        (uuid_mod.UUID(s), uuid_mod.UUID(p), uuid_mod.UUID(o), uuid_mod.UUID(g))
        for s, p, o, g in quad_rows
    ]
    # ON CONFLICT DO NOTHING, because an RDF graph is a SET: a document that
    # states the same triple twice describes one triple, not an error. Several
    # DAWG data files do exactly that.
    #
    # This was unguarded and silently fine while rdf_quad's key included a
    # random quad_uuid — every row was unique, so nothing ever conflicted. Once
    # the key enforced (s,p,o,c) the duplicate raised, executemany aborted, and
    # the space was left EMPTY: eleven conformance cases failed reporting
    # "expected 5, got 0", none of which was a conformance problem.
    await conn.executemany(
        f"INSERT INTO {quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, dataset) "
        f"VALUES ($1, $2, $3, $4, 'primary') ON CONFLICT DO NOTHING",
        quad_rows_uuid,
    )

    # ANALYZE for query planner
    await conn.execute(f"ANALYZE {term_table}")
    await conn.execute(f"ANALYZE {quad_table}")

    logger.debug("Loaded %d terms, %d quads from %s", len(terms), len(quad_rows), ttl_file.name)
    return len(quad_rows)
