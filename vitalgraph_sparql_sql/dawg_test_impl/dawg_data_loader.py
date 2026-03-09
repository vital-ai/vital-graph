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
            s_uuid = ensure(triple.subject.value, "B")
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
            o_uuid = ensure(obj.value, "B")
        else:
            o_uuid = ensure(obj.value, "U")

        quad_rows.append((s_uuid, p_uuid, o_uuid, graph_uuid))

    # Load datatype URI → ID mapping from the datatype lookup table
    datatype_table = f"{space_id}_datatype"
    dt_uri_to_id: Dict[str, int] = {}
    rows = await conn.fetch(f"SELECT datatype_uri, datatype_id FROM {datatype_table}")
    for row in rows:
        dt_uri_to_id[row["datatype_uri"]] = row["datatype_id"]

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
    await conn.executemany(
        f"INSERT INTO {quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, dataset) "
        f"VALUES ($1, $2, $3, $4, 'primary')",
        quad_rows_uuid,
    )

    # ANALYZE for query planner
    await conn.execute(f"ANALYZE {term_table}")
    await conn.execute(f"ANALYZE {quad_table}")

    logger.debug("Loaded %d terms, %d quads from %s", len(terms), len(quad_rows), ttl_file.name)
    return len(quad_rows)
