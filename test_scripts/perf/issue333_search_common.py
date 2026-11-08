"""Shared pieces of the `issues/333` CJK search scripts.

A per-graph hybrid search over chat messages, built from vitalgraph's own
client and SPARQL extensions only:

  * `provision`: a vector index and an FTS index under one name, and a
    `kgentity` search mapping per message class reading its text property,
    with both indexes attached
  * `hybrid_query`: `BIND(vg:hybridSearch(?s, <text>, <index>, <alpha>) AS
    ?score)` inside one `GRAPH <g>`, `FILTER(?score > 0) ORDER BY DESC(?score)
    LIMIT k`, projecting the text and the message properties a search result
    page carries
"""

from __future__ import annotations

KG = "http://vital.ai/ontology/haley-ai-kg#"
VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
VG = "http://vital.ai/ontology/vitalgraph#"

USER_MESSAGE = KG + "KGChatUserMessage"
BOT_MESSAGE = KG + "KGChatBotMessage"
MESSAGE_TYPES = (USER_MESSAGE, BOT_MESSAGE)
TEXT = KG + "hasKGChatMessageText"
DATETIME = KG + "hasKGChatMessageDateTime"
INTERACTION = KG + "hasKGChatInteractionURI"
JSON_PROP = KG + "hasKGJSON"

#: A multilingual sentence model the server provides.
VECTOR_PROVIDER = "paraphrase_multilingual_minilm_l12_v2"
VECTOR_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_DIMENSIONS = 384
DEFAULT_LANGUAGES = ("english", "spanish", "portuguese", "cjk")


async def provision(client, space: str, index: str, languages=DEFAULT_LANGUAGES) -> list:
    """Make the indexes and mappings that are missing; return what was done."""
    done = []
    vec = {i.index_name for i in (await client.vector_indexes.list_indexes(space)).indexes}
    fts = {i.index_name for i in (await client.fts_indexes.list_indexes(space)).indexes}
    if index not in vec:
        await client.vector_indexes.create_index(
            space_id=space, index_name=index, dimensions=VECTOR_DIMENSIONS,
            distance_metric="cosine", provider=VECTOR_PROVIDER, model_name=VECTOR_MODEL)
        done.append(f"vector index {index}")
    if index not in fts:
        r = await client.fts_indexes.create_index(
            space_id=space, index_name=index, languages=list(languages))
        if not getattr(r, "success", True):
            raise RuntimeError(f"FTS index refused: {getattr(r, 'message', r)}")
        done.append(f"FTS index {index} {list(languages)}")
    have = {(m.index_name, m.mapping_type, m.type_uri): m
            for m in (await client.search_mappings.list_mappings(space)).mappings}
    for t in MESSAGE_TYPES:
        m = have.get((index, "kgentity", t))
        if m is None:
            m = await client.search_mappings.create_mapping(
                space_id=space, index_name=index, mapping_type="kgentity", type_uri=t,
                enabled=True, source_type="properties")
            done.append(f"mapping {index}/{t.rsplit('#', 1)[-1]}")
        if TEXT not in {p.property_uri for p in (m.properties or [])}:
            await client.search_mappings.add_property(
                space_id=space, mapping_id=m.mapping_id, property_uri=TEXT, ordinal=0)
        attached = {i.index_type for i in (m.indexes or []) if i.index_name == index}
        for kind in ("vector", "fts"):
            if kind not in attached:
                await client.search_mappings.add_index(
                    space_id=space, mapping_id=m.mapping_id, index_type=kind, index_name=index)
    return done


def literal(text: str) -> str:
    return '"' + (text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                  .replace("\r", "\\r").replace("\t", "\\t")) + '"'


def hybrid_query(graph: str, text: str, index: str, alpha: float = 0.5,
                 limit: int = 12, with_date: bool = True) -> str:
    """One graph's messages, scored by the hybrid, best `limit` first."""
    values = " ".join(f"<{t}>" for t in MESSAGE_TYPES)
    pattern = [f"VALUES ?type {{ {values} }}", f"?s <{VITALTYPE}> ?type .",
               f"?s <{TEXT}> ?text ."]
    select = "?s ?score ?text"
    if with_date:
        pattern.append(f"?s <{DATETIME}> ?at .")
        select += " ?at"
    pattern += [f"?s <{INTERACTION}> ?parent .", f"?s <{JSON_PROP}> ?json ."]
    select += " ?parent ?json"
    body = "\n    ".join(pattern + [
        f"BIND(<{VG}hybridSearch>(?s, {literal(text)}, {literal(index)}, {alpha}) AS ?score)",
        "FILTER(?score > 0)"])
    return (f"SELECT {select} WHERE {{ GRAPH <{graph}> {{\n    {body}\n}} }}\n"
            f"ORDER BY DESC(?score) LIMIT {int(limit)}")


def bindings(response) -> list:
    results = getattr(response, "results", None)
    rows = results.get("bindings") if isinstance(results, dict) else getattr(results, "bindings", None)
    return [{k: (v.get("value") if isinstance(v, dict) else v) for k, v in b.items()}
            for b in (rows or [])]
