#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nurture_portal_fts_cases import CASES  # noqa: E402
from test_nurture_kgquery_fts import build_criteria  # noqa: E402
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response  # noqa: E402
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient  # noqa: E402
from vitalgraph.db.sparql_sql.generator import generate_sql  # noqa: E402
from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint  # noqa: E402
from vitalgraph.sparql.kg_query_builder import (  # noqa: E402
    EntityPropertyFilter as BuilderEntityPropertyFilter,
    FTSCriteria as BuilderFTSCriteria,
    FTSTarget as BuilderFTSTarget,
    FrameQueryCriteria,
    SortCriteria as BuilderSortCriteria,
)


def to_builder(case, index_name: str) -> FrameQueryCriteria:
    criteria = build_criteria(case, index_name)
    source_entity_criteria = criteria.source_entity_criteria
    fts_criteria = criteria.fts_criteria
    if source_entity_criteria is None or fts_criteria is None:
        raise ValueError("portal FTS cases require source entity and FTS criteria")
    return FrameQueryCriteria(
        entity_type=source_entity_criteria.entity_type,
        entity_property_filters=[
            BuilderEntityPropertyFilter(
                property_uri=item.property_uri,
                operator=item.operator,
                value=item.value,
            )
            for item in (criteria.entity_property_filters or [])
        ]
        or None,
        sort_criteria=[
            BuilderSortCriteria(
                sort_type=item.sort_type,
                slot_type=item.slot_type,
                slot_class_uri=item.slot_class_uri,
                frame_path=item.frame_path,
                property_uri=item.property_uri,
                sort_order=item.sort_order,
                priority=item.priority,
            )
            for item in (criteria.sort_criteria or [])
        ]
        or None,
        fts_criteria=BuilderFTSCriteria(
            text=fts_criteria.text,
            index_name=fts_criteria.index_name,
            targets=[
                BuilderFTSTarget(target.slot_type, target.frame_type, target.kind)
                for target in fts_criteria.targets
            ],
            include_match_text=fts_criteria.include_match_text,
        ),
    )


async def main() -> int:
    graph = os.getenv("VG_SEARCH_GRAPH", "urn:acme_kg")
    space = os.getenv("VG_SEARCH_SPACE", "test_space")
    index_name = os.getenv("VG_FTS_INDEX", "message_content")
    sidecar_url = os.getenv("VG_TEST_SIDECAR_URL", "http://localhost:7071")
    endpoint = KGQueriesEndpoint(None, None)
    sidecar = AsyncSidecarClient(sidecar_url)
    failures = []
    try:
        for case in CASES:
            builder_criteria = to_builder(case, index_name)
            builder_fts_criteria = builder_criteria.fts_criteria
            if builder_fts_criteria is None:
                failures.append(f"{case.name}: builder lost FTS criteria")
                continue
            sparql = endpoint.query_builder.build_frame_query_sparql(builder_criteria, graph, 25, 0)
            raw = await sidecar.compile(sparql)
            compiled = map_compile_response(raw)
            if not compiled.ok:
                failures.append(f"{case.name}: SPARQL compile failed: {compiled.error}")
                continue
            generated = await generate_sql(compiled, space)
            sql = generated.sql
            checks = {
                "fts table": f"{space}_fts_{index_name}" in sql,
                "boolean match": "tsv @@" in sql,
                "websearch parser": "websearch_to_tsquery" in sql,
                "no rank": "ts_rank" not in sql,
            }
            matches_sparql = endpoint.query_builder.build_fts_matches_sparql(
                builder_fts_criteria,
                ["urn:test:frame:page-row"],
                "frame",
                graph,
            )
            matches_raw = await sidecar.compile(matches_sparql)
            matches_compiled = map_compile_response(matches_raw)
            if not matches_compiled.ok:
                failures.append(
                    f"{case.name}: match metadata SPARQL compile failed: "
                    f"{matches_compiled.error}"
                )
                continue
            matches_sql = (await generate_sql(matches_compiled, space)).sql
            count_sparql = endpoint._build_frame_count_query(builder_criteria, graph, cap=1000)
            count_raw = await sidecar.compile(count_sparql)
            count_compiled = map_compile_response(count_raw)
            if not count_compiled.ok:
                failures.append(
                    f"{case.name}: count SPARQL compile failed: " f"{count_compiled.error}"
                )
                continue
            count_sql = (await generate_sql(count_compiled, space)).sql
            checks.update(
                {
                    "metadata bounded to page": "urn:test:frame:page-row" in matches_sql,
                    "metadata uses fts": f"{space}_fts_{index_name}" in matches_sql,
                    "metadata has no rank": "ts_rank" not in matches_sql,
                    "count uses fts": f"{space}_fts_{index_name}" in count_sql,
                    "count has no rank": "ts_rank" not in count_sql,
                }
            )
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                failures.append(f"{case.name}: {', '.join(failed)}")
            else:
                print(f"PASS  {case.name}")
    finally:
        close = getattr(sidecar, "aclose", None) or getattr(sidecar, "close", None)
        if close:
            result = close()
            if hasattr(result, "__await__"):
                await result

    if failures:
        for failure in failures:
            print(f"FAIL  {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
