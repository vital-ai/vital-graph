"""
DAWG SPARQL 1.1 test runner — main orchestrator.

Supports three engines:
  - pyoxigraph (default): In-memory RDF store, no DB needed.
  - sql: Our v1 SPARQL→SQL pipeline via SparqlOrchestrator.
  - sql_v2: The v2 SPARQL→SQL pipeline (collect → emit → materialize).
  Both sql engines require PostgreSQL and the Jena sidecar to be running.

Usage:
    # Phase 1: pyoxigraph baseline
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --category bind

    # Phase 2: SQL pipeline comparison (v1)
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --engine sql
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --engine sql --category bind

    # Phase 3: v2 SQL pipeline
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --engine sql_v2
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --engine sql_v2 --category bind

    # Common options
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --test bind01
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --failures-only
    python -m vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner --report results/report.json
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from .dawg_manifest_parser import (
    DawgTestCase,
    discover_categories,
    get_manifest_path,
    parse_manifest,
)
from .dawg_oxigraph_executor import SparqlExecutionError, execute_query
from .dawg_report import (
    TestReport,
    TestResult,
    build_report,
    print_report,
    save_report_json,
)
from .dawg_result_comparator import compare_results
from .dawg_srx_parser import parse_result_file, SparqlResults

logger = logging.getLogger(__name__)

# Track currently loaded dataset to avoid redundant reloads
_current_data_file: Optional[Path] = None

# P0 categories — the ones most relevant to our SQL pipeline
P0_CATEGORIES = [
    "bind",
    "aggregates",
    "functions",
    "negation",
    "exists",
    "grouping",
]

# All query-related categories (excludes update, protocol, etc.)
QUERY_CATEGORIES = P0_CATEGORIES + [
    "bindings",
    "cast",
    "construct",
    "csv-tsv-res",
    "json-res",
    "project-expression",
    "property-path",
    "subquery",
]

# Categories to skip entirely
SKIP_CATEGORIES = {
    "entailment",    # Requires OWL reasoning
    "service",       # Requires federated endpoint
    "protocol",      # Tests HTTP protocol, not queries
    "http-rdf-update",
    "service-description",
    "syntax-fed",
}

# Update categories — use dedicated update test runner
UPDATE_CATEGORIES = {
    "add",
    "basic-update",
    "clear",
    "copy",
    "delete",
    "delete-data",
    "delete-insert",
    "delete-where",
    "drop",
    "move",
    "update-silent",
}


def _project_root() -> Path:
    """Return the project root (three levels up from this file)."""
    return Path(__file__).resolve().parents[2]


def _dawg_root() -> Path:
    """Return the path to the DAWG test suite."""
    return _project_root() / "vitalgraph_sparql_sql" / "dawg_tests"


def _jena_arq_root() -> Path:
    """Return the path to the Jena ARQ test suite."""
    return _project_root() / "jena-main-source" / "jena-arq" / "testing" / "ARQ"


# Jena ARQ categories to run (subdirs of ARQ/ with manifest.ttl)
JENA_ARQ_CATEGORIES = [
    "Ask",
    "Construct",
    "Describe",
    "Optional",
    "Union",
    "Negation",
    "GroupBy",
    "SubQuery",
    "Paths",
    "Basic",
    "Bound",
    "Distinct",
    "Sort",
    "Select",
    "SelectExpr",
    "Assign",
]


def _check_test_prerequisites(test: DawgTestCase) -> Optional[TestResult]:
    """Check common prerequisites. Returns a SKIP TestResult or None."""
    if test.test_type != "QueryEvaluation":
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message=f"Test type: {test.test_type} (only QueryEvaluation supported)",
        )
    if test.query_file is None or not test.query_file.exists():
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message="Query file missing",
        )
    if test.result_file is None or not test.result_file.exists():
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message="Result file missing",
        )
    return None


def run_single_test(test: DawgTestCase) -> TestResult:
    """Run a single DAWG test case against pyoxigraph.

    Returns a TestResult with PASS/FAIL/SKIP/ERROR status.
    """
    skip = _check_test_prerequisites(test)
    if skip:
        return skip

    expected = parse_result_file(test.result_file)
    if expected is None:
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message=f"Cannot parse result file: {test.result_file.suffix}",
        )

    try:
        sparql = test.query_file.read_text(encoding="utf-8")
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            error_message=f"Cannot read query: {e}",
        )

    t0 = time.time()
    try:
        actual = execute_query(
            sparql,
            data_file=test.data_file,
            named_graph_files=test.named_graph_files or None,
        )
    except SparqlExecutionError as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000, error_message=str(e),
        )
    elapsed_ms = (time.time() - t0) * 1000

    comparison = compare_results(actual, expected)
    return TestResult(
        name=test.name, category=test.category,
        status="PASS" if comparison.match else "FAIL",
        expected_rows=comparison.expected_count,
        actual_rows=comparison.actual_count,
        time_ms=elapsed_ms,
        error_message="" if comparison.match else comparison.message,
    )


async def run_single_test_sql(test: DawgTestCase, orchestrator, db_conn) -> TestResult:
    """Run a single DAWG test case against our SQL pipeline.

    Loads test data into PostgreSQL, runs SPARQL through the orchestrator,
    compares against pyoxigraph as the oracle.
    """
    from .dawg_data_loader import load_ttl_into_space
    from .dawg_space_manager import truncate_space, SPACE_ID
    from .dawg_sql_executor import execute_query_via_pipeline, SqlPipelineError

    skip = _check_test_prerequisites(test)
    if skip:
        return skip

    expected = parse_result_file(test.result_file)
    if expected is None:
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message=f"Cannot parse result file: {test.result_file.suffix}",
        )

    try:
        sparql = test.query_file.read_text(encoding="utf-8")
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            error_message=f"Cannot read query: {e}",
        )

    # Load data into PostgreSQL (skip reload if same dataset)
    global _current_data_file
    data_path = test.data_file
    if data_path != _current_data_file:
        await truncate_space(db_conn, SPACE_ID)
        if data_path and data_path.exists():
            await load_ttl_into_space(db_conn, data_path, SPACE_ID)
        _current_data_file = data_path

    # Get pyoxigraph baseline for comparison
    try:
        oxigraph_result = execute_query(
            sparql,
            data_file=test.data_file,
            named_graph_files=test.named_graph_files or None,
        )
    except SparqlExecutionError:
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message="pyoxigraph cannot execute this query (skip for SQL too)",
        )

    # Execute through SQL pipeline
    t0 = time.time()
    try:
        sql_result = await execute_query_via_pipeline(sparql, orchestrator)
    except SqlPipelineError as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000, error_message=str(e),
        )
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000, error_message=f"Unexpected: {e}",
        )
    elapsed_ms = (time.time() - t0) * 1000

    # Compare SQL result against pyoxigraph baseline
    comparison = compare_results(sql_result, oxigraph_result)
    if comparison.match:
        # Also check against .srx for full confidence
        srx_cmp = compare_results(sql_result, expected)
        return TestResult(
            name=test.name, category=test.category,
            status="PASS",
            expected_rows=comparison.expected_count,
            actual_rows=comparison.actual_count,
            time_ms=elapsed_ms,
        )
    else:
        # Check if pyoxigraph also disagrees with .srx (spec ambiguity)
        oxigraph_vs_srx = compare_results(oxigraph_result, expected)
        if not oxigraph_vs_srx.match:
            suffix = " [pyoxigraph also differs from .srx]"
            status = "ACCEPTED"
        else:
            suffix = " [our bug: pyoxigraph matches .srx]"
            status = "FAIL"
        return TestResult(
            name=test.name, category=test.category, status=status,
            expected_rows=comparison.expected_count,
            actual_rows=comparison.actual_count,
            time_ms=elapsed_ms,
            error_message=comparison.message + suffix,
        )


async def run_single_test_sql_v2(test: DawgTestCase, db_conn) -> TestResult:
    """Run a single DAWG test case against the v2 SQL pipeline."""
    from .dawg_data_loader import load_ttl_into_space
    from .dawg_space_manager import truncate_space, SPACE_ID
    from .dawg_sql_v2_executor import execute_query_via_v2_pipeline, SqlV2PipelineError

    skip = _check_test_prerequisites(test)
    if skip:
        return skip

    expected = parse_result_file(test.result_file)
    if expected is None:
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message=f"Cannot parse result file: {test.result_file.suffix}",
        )

    try:
        sparql = test.query_file.read_text(encoding="utf-8")
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            error_message=f"Cannot read query: {e}",
        )

    # Load data into PostgreSQL (skip reload if same dataset)
    global _current_data_file
    data_path = test.data_file
    named_paths = tuple(test.named_graph_files or [])
    cache_key = (data_path, named_paths)
    if cache_key != getattr(run_single_test_sql_v2, '_cache_key', None):
        await truncate_space(db_conn, SPACE_ID)
        if data_path and data_path.exists():
            await load_ttl_into_space(db_conn, data_path, SPACE_ID)
        # Load named graph data with the file's base IRI as context
        for ng_file in named_paths:
            if ng_file.exists():
                ng_graph_uri = f"file://{ng_file}"
                await load_ttl_into_space(db_conn, ng_file, SPACE_ID,
                                          graph_uri=ng_graph_uri)
        run_single_test_sql_v2._cache_key = cache_key
        _current_data_file = data_path

    # Get pyoxigraph baseline
    try:
        oxigraph_result = execute_query(
            sparql,
            data_file=test.data_file,
            named_graph_files=test.named_graph_files or None,
        )
    except SparqlExecutionError:
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message="pyoxigraph cannot execute this query (skip for v2 too)",
        )

    # Execute through v2 pipeline
    # When BOTH default and named graphs are loaded, constrain outer BGPs to
    # the default graph and exclude it from GRAPH ?g.  Without default data
    # there's nothing to leak, so no constraint needed.
    from .dawg_data_loader import DEFAULT_GRAPH_URI
    # When named graphs exist, constrain outer BGPs to the default graph.
    # If no default data was loaded, the default graph is empty — correct.
    v2_default_graph = DEFAULT_GRAPH_URI if named_paths else None
    t0 = time.time()
    try:
        sql_result = await execute_query_via_v2_pipeline(
            sparql, space_id=SPACE_ID, conn=db_conn,
            default_graph=v2_default_graph,
        )
    except SqlV2PipelineError as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000, error_message=str(e),
        )
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000, error_message=f"Unexpected: {e}",
        )
    elapsed_ms = (time.time() - t0) * 1000

    comparison = compare_results(sql_result, oxigraph_result)
    if comparison.match:
        return TestResult(
            name=test.name, category=test.category, status="PASS",
            expected_rows=comparison.expected_count,
            actual_rows=comparison.actual_count,
            time_ms=elapsed_ms,
        )
    else:
        oxigraph_vs_srx = compare_results(oxigraph_result, expected)
        if not oxigraph_vs_srx.match:
            suffix = " [pyoxigraph also differs from .srx]"
            status = "ACCEPTED"
        else:
            suffix = " [our bug: pyoxigraph matches .srx]"
            status = "FAIL"
        return TestResult(
            name=test.name, category=test.category, status=status,
            expected_rows=comparison.expected_count,
            actual_rows=comparison.actual_count,
            time_ms=elapsed_ms,
            error_message=comparison.message + suffix,
        )


async def run_category(dawg_root: Path, category: str,
                       engine: str = "pyoxigraph",
                       orchestrator=None, db_conn=None,
                       manifest_path_override: Path = None) -> List[TestResult]:
    """Run all tests in a category."""
    manifest_path = manifest_path_override or get_manifest_path(dawg_root, category)
    tests = parse_manifest(manifest_path, category=category)

    if not tests:
        logger.warning("No tests found for category: %s", category)
        return []

    # Reset data file tracker at start of each category
    global _current_data_file
    _current_data_file = None

    results: List[TestResult] = []
    for test in tests:
        if engine == "sql":
            result = await run_single_test_sql(test, orchestrator, db_conn)
        elif engine == "sql_v2":
            result = await run_single_test_sql_v2(test, db_conn)
        else:
            result = run_single_test(test)
        results.append(result)

        if result.status == "PASS":
            logger.debug("  PASS  %s/%s (%.0fms)", category, test.name, result.time_ms)
        elif result.status == "ACCEPTED":
            logger.debug("  ACPT  %s/%s (%.0fms): %s", category, test.name, result.time_ms, result.error_message)
        elif result.status == "SKIP":
            logger.debug("  SKIP  %s/%s: %s", category, test.name, result.error_message)
        else:
            logger.info("  %s  %s/%s: %s", result.status, category, test.name, result.error_message)

    return results


async def run_all(
    dawg_root: Path,
    categories: Optional[List[str]] = None,
    test_filter: Optional[str] = None,
    engine: str = "pyoxigraph",
    jena_categories: Optional[List[str]] = None,
) -> TestReport:
    """Run tests across multiple categories and suites.

    Args:
        dawg_root: Path to the DAWG test suite root.
        categories: DAWG categories to run. If None, uses QUERY_CATEGORIES.
        test_filter: If set, only run tests whose name contains this string.
        engine: "pyoxigraph", "sql", or "sql_v2".
        jena_categories: Jena ARQ categories to run. If None, skips Jena.

    Returns:
        TestReport with aggregated results.
    """
    if categories is None:
        categories = QUERY_CATEGORIES

    orchestrator = None
    db_conn = None

    if engine in ("sql", "sql_v2"):
        orchestrator, db_conn = await _setup_sql_engine()

    try:
        all_results: List[TestResult] = []

        # --- DAWG suite ---
        if categories:
            for category in categories:
                if category in SKIP_CATEGORIES:
                    logger.info("Skipping category: %s", category)
                    continue

                # Update categories use dedicated runner
                if category in UPDATE_CATEGORIES:
                    if engine != "sql_v2":
                        logger.info("Skipping update category %s (only sql_v2)", category)
                        continue
                    logger.info("Running update category: %s", category)
                    cat_results = await _run_update_category(
                        dawg_root, category, db_conn=db_conn,
                    )
                    if test_filter:
                        cat_results = [r for r in cat_results
                                       if test_filter.lower() in r.name.lower()]
                    all_results.extend(cat_results)
                    passed = sum(1 for r in cat_results if r.status == "PASS")
                    total = len(cat_results)
                    logger.info("  %s: %d/%d passed", category, passed, total)
                    continue

                logger.info("Running category: %s", category)
                cat_results = await run_category(
                    dawg_root, category,
                    engine=engine, orchestrator=orchestrator, db_conn=db_conn,
                )

                if test_filter:
                    cat_results = [r for r in cat_results if test_filter.lower() in r.name.lower()]

                all_results.extend(cat_results)

                passed = sum(1 for r in cat_results if r.status == "PASS")
                accepted = sum(1 for r in cat_results if r.status == "ACCEPTED")
                total = len(cat_results)
                acpt_note = f" (+{accepted} accepted)" if accepted else ""
                logger.info("  %s: %d/%d passed%s", category, passed, total, acpt_note)

        # --- Jena ARQ suite ---
        if jena_categories:
            arq_root = _jena_arq_root()
            if not arq_root.exists():
                logger.warning("Jena ARQ root not found: %s", arq_root)
            else:
                for jena_cat in jena_categories:
                    manifest = arq_root / jena_cat / "manifest.ttl"
                    if not manifest.exists():
                        logger.warning("Jena manifest not found: %s", manifest)
                        continue

                    display_cat = f"jena/{jena_cat}"
                    logger.info("Running category: %s", display_cat)
                    cat_results = await run_category(
                        arq_root, jena_cat,
                        engine=engine, orchestrator=orchestrator, db_conn=db_conn,
                        manifest_path_override=manifest,
                    )
                    # Prefix category with jena/ for display
                    for r in cat_results:
                        r.category = display_cat

                    if test_filter:
                        cat_results = [r for r in cat_results
                                       if test_filter.lower() in r.name.lower()]

                    all_results.extend(cat_results)

                    passed = sum(1 for r in cat_results if r.status == "PASS")
                    accepted = sum(1 for r in cat_results if r.status == "ACCEPTED")
                    total = len(cat_results)
                    acpt_note = f" (+{accepted} accepted)" if accepted else ""
                    logger.info("  %s: %d/%d passed%s", display_cat, passed, total, acpt_note)

        return build_report(all_results, engine=engine)
    finally:
        if orchestrator:
            await orchestrator.close()
        if db_conn:
            pass  # asyncpg connections returned to pool automatically


async def _run_update_category(
    dawg_root: Path,
    category: str,
    db_conn=None,
) -> List[TestResult]:
    """Run all update tests in a category using the dedicated update runner."""
    from .dawg_update_test import parse_update_manifest, run_single_update_test_v2

    manifest_path = get_manifest_path(dawg_root, category)
    tests = parse_update_manifest(manifest_path, category=category)

    if not tests:
        logger.warning("No update tests found for category: %s", category)
        return []

    results: List[TestResult] = []
    for test in tests:
        result = await run_single_update_test_v2(test, db_conn)
        results.append(result)

        if result.status == "PASS":
            logger.debug("  PASS  %s/%s (%.0fms)", category, test.name, result.time_ms)
        elif result.status == "SKIP":
            logger.debug("  SKIP  %s/%s: %s", category, test.name, result.error_message)
        else:
            logger.info("  %s  %s/%s: %s", result.status, category, test.name, result.error_message)

    return results


async def _setup_sql_engine():
    """Initialize PostgreSQL space and SparqlOrchestrator for SQL engine mode."""
    from .dawg_space_manager import SPACE_ID, create_space, drop_space
    from .. import db

    # Configure the pipeline's db_provider with a DbImplInterface implementation
    from vitalgraph.db.sparql_sql import db_provider
    if not db_provider.is_configured():
        from ..db import DevDbImpl
        dev_impl = DevDbImpl()
        await dev_impl.connect()
        db_provider.configure(dev_impl)

    # Get an asyncpg connection from the pool (managed by db module)
    conninfo = db.get_connection_string()
    logger.info("Connecting to PostgreSQL (asyncpg): %s", conninfo.split("password=")[0])
    pool = await db.get_pool()
    db_conn = await pool.acquire()

    # Always recreate for a clean start (drops stale MVs, stats tables, etc.)
    logger.info("Recreating dawg_test space tables...")
    await drop_space(db_conn, SPACE_ID)
    await create_space(db_conn, SPACE_ID)

    # Clear the v2 generator's stats cache so it doesn't use stale entries
    from vitalgraph.db.sparql_sql.generator import _stats_cache
    _stats_cache.pop(SPACE_ID, None)

    # Create orchestrator
    from ..jena_sparql_orchestrator import SparqlOrchestrator
    orchestrator = SparqlOrchestrator(space_id=SPACE_ID)

    return orchestrator, db_conn


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run DAWG SPARQL 1.1 tests against pyoxigraph or SQL pipeline",
    )
    p.add_argument(
        "--engine", "-e",
        choices=["pyoxigraph", "sql", "sql_v2"],
        default="pyoxigraph",
        help="Engine: 'pyoxigraph' (default), 'sql' (v1), or 'sql_v2' (v2)",
    )
    p.add_argument(
        "--category", "-c",
        help="Run a single category (e.g., 'bind', 'aggregates')",
    )
    p.add_argument(
        "--all-categories", action="store_true",
        help="Run all query categories (not just P0)",
    )
    p.add_argument(
        "--suite", "-s",
        choices=["dawg", "jena", "all"],
        default="dawg",
        help="Test suite: 'dawg' (default), 'jena' (ARQ tests), or 'all'",
    )
    p.add_argument(
        "--test", "-t",
        help="Filter: only run tests whose name contains this string",
    )
    p.add_argument(
        "--failures-only", action="store_true",
        help="Only show failures in the report",
    )
    p.add_argument(
        "--report", "-r",
        help="Save JSON report to this path",
    )
    p.add_argument(
        "--dawg-root",
        help="Path to DAWG test suite (default: auto-detected)",
    )
    p.add_argument(
        "--list-categories", action="store_true",
        help="List available categories and exit",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose logging",
    )
    return p.parse_args(argv)


async def async_main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    dawg_root = Path(args.dawg_root) if args.dawg_root else _dawg_root()
    if not dawg_root.exists():
        logger.error("DAWG test suite not found at %s", dawg_root)
        logger.error("Clone it: git clone --depth 1 https://github.com/w3c/rdf-tests %s", dawg_root)
        sys.exit(1)

    # List categories
    if args.list_categories:
        cats = discover_categories(dawg_root)
        print("Available categories:")
        for c in cats:
            marker = " [P0]" if c in P0_CATEGORIES else ""
            skip = " [SKIP]" if c in SKIP_CATEGORIES else ""
            update = " [UPDATE]" if c in UPDATE_CATEGORIES else ""
            print(f"  {c}{marker}{skip}{update}")
        sys.exit(0)

    # Determine which categories to run
    if args.category:
        categories = [args.category]
    elif args.all_categories:
        categories = QUERY_CATEGORIES + sorted(UPDATE_CATEGORIES)
    else:
        categories = QUERY_CATEGORIES

    # Determine suite scope
    suite = args.suite
    dawg_cats = categories if suite in ("dawg", "all") else []
    jena_cats = JENA_ARQ_CATEGORIES if suite in ("jena", "all") else None

    # For --suite jena --category Ask, support single Jena category
    if suite == "jena" and args.category:
        jena_cats = [args.category]
        dawg_cats = []

    # Run
    report = await run_all(
        dawg_root, categories=dawg_cats,
        test_filter=args.test, engine=args.engine,
        jena_categories=jena_cats,
    )

    # Print report
    print_report(report, show_failures=True)

    # Save JSON report
    if args.report:
        save_report_json(report, Path(args.report))

    # Exit code: 0 if no errors, 1 if any failures/errors
    if report.failed > 0 or report.errors > 0:
        sys.exit(1)
    sys.exit(0)


def main(argv=None):
    import asyncio
    asyncio.run(async_main(argv))


if __name__ == "__main__":
    main()
