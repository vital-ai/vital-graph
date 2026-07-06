# Testing Plan — Tier 2: SPARQL Conformance (DAWG + Jena ARQ)

> Split from [testing_plan.md](testing_plan.md). See main doc for overall
> architecture, CI pipeline, fixtures, and migration strategy.

## Purpose

Prove correctness against the W3C SPARQL 1.1 test suite and
Apache Jena's ARQ test suite.

## Approach

- Wrap the existing DAWG runner as a pytest parameterized test.
  Each DAWG test case becomes a `pytest.mark.parametrize` entry.
- Compare VitalGraph results against expected `.srx` / `.ttl` files.
- Use pyoxigraph as a reference oracle for any result ambiguity.
- Track **expected failures** with `pytest.mark.xfail` so the suite
  is green even while we iterate on unsupported features.

## Current baseline (v87 report)

- P0 categories: 104 pass / 18 fail / 25 skip / 9 error = 79.4%
- Target: **95%+ pass rate** on P0, all failures documented as xfail.

## DAWG categories to cover

| Category | Current | Target |
|----------|---------|--------|
| bind | 7/10 | 10/10 |
| aggregates | 32/32* | maintain |
| functions | partial | 90%+ |
| negation | partial | 95%+ |
| exists | partial | 95%+ |
| grouping | partial | 95%+ |
| construct | partial | 90%+ |
| property-path | not started | 80%+ |
| subquery | partial | 90%+ |
| update (add/delete/insert/etc.) | partial | 85%+ |

*Aggregates 32/32 non-skipped as of last session.

## Jena ARQ categories

Ask, Construct, Describe, Optional, Union, Negation,
GroupBy, SubQuery, Paths, Basic, Bound, Distinct, Sort, Select, SelectExpr, Assign.

## DAWG parametrization pattern

```python
# tests/conformance/test_dawg_bind.py
import pytest
from vitalgraph_sparql_sql.dawg_test_impl.dawg_test_runner import ...

cases = discover_dawg_cases(category="bind")

@pytest.mark.conformance
@pytest.mark.parametrize("case", cases, ids=lambda c: c.name)
def test_dawg_bind(case, dawg_executor):
    result = dawg_executor.run(case)
    if case.name in KNOWN_XFAILS:
        pytest.xfail(KNOWN_XFAILS[case.name])
    assert result.status == "PASS", result.error_message
```

---

## Implementation Progress

- ✅ `tests/conformance/test_dawg_pyoxigraph.py` — 245 tests (207 pass, 18 skip, 20 xfail)
- ✅ `tests/conformance/test_dawg_sql_v2.py` — P0 categories against pyoxigraph oracle (skips without DB)
- Categories covered: bind, aggregates, functions, negation, exists, grouping, bindings, cast, construct, csv-tsv-res, json-res, project-expression, property-path, subquery
- Pass rate: **91.2%** (207/227 non-skipped)
- All failures tracked as `xfail` with reasons — suite is green
