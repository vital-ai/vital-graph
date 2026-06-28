# Jena Source Code Review Plan

## Purpose

Learn from Apache Jena's SPARQL implementation to improve our SPARQL-to-SQL pipeline.
Three goals:

1. **Datatype flow** — Understand how Jena tracks, propagates, and infers XSD datatypes
   through expression evaluation, aggregates, and result construction. This has been our
   #1 source of DAWG test failures.

2. **AST → query translation** — Study how Jena's algebra tree (Op nodes) is compiled
   and executed, to validate and improve our 3-pass pipeline (collect → resolve → emit).

3. **Code organization** — Our `jena_sql_emit.py` is 2,693 lines and growing. Study how
   Jena decomposes equivalent functionality into focused, maintainable classes.

**Source**: `/Users/hadfield/Local/vital-git/vital-graph/jena-main-source/`

**Our pipeline**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_sparql_sql/`

**Current DAWG status**: 77/156 (58.8%) — up from 56 at session start.

---

## 1. Current Problem Inventory

These are the specific DAWG test failure patterns driving this review:

### 1.1 Datatype Mismatches (biggest cluster — ~20 tests)

| Problem | Example Test | Root Cause |
|---------|-------------|------------|
| AVG returns wrong numeric type | AVG DISTINCT with GROUP BY | We hardcode `xsd:decimal`; Jena's `numDivide` promotes int→decimal but preserves double |
| SUM/MIN/MAX lose input type | SUM with GROUP BY | We don't propagate input `xsd:double` through aggregates |
| STRAFTER/STRBEFORE lose lang/dt | STRAFTER() datatyping | Jena's `calcReturn()` copies lang+datatype from input node; we infer statically |
| STRDT/STRLANG error on wrong input | STRDT() TypeErrors | STRDT on lang-tagged literal should error→unbound; our SQL always returns a value |
| IF() branch types not propagated | IF() | We return static datatype from branch constants; need row-level CASE for variable branches |
| CONCAT mixed lang handling | CONCAT() 2 | Jena: all same lang→preserve, mixed→xsd:string; we return NULL datatype |
| Empty group default values | AVG with empty group | Jena returns `0` for AVG of empty group; SQL returns NULL |

### 1.2 SQL Generation Errors (15 ERR tests)

| Problem | Example Test | Root Cause |
|---------|-------------|------------|
| GROUP BY with expression | GROUP BY with a built-in function | `GROUP BY (DATATYPE(?o) AS ?d)` — computed key var `d` not projected |
| GROUP_CONCAT table ref | GROUP_CONCAT 2 | Missing FROM-clause for `t1` in GROUP_CONCAT subquery |
| BIND scoping | bind03, bind07 | Variable visibility across BIND/FILTER scopes mishandled |
| Arithmetic on non-numeric | plus-2-corrected | `CAST("a" AS NUMERIC)` throws instead of returning NULL |
| COUNT(*) in AVG | Protect from error in AVG | `AVG(CAST(* AS NUMERIC))` — syntax error |

### 1.3 Structural Issues (MINUS, EXISTS, OPTIONAL)

| Problem | Tests | Status |
|---------|-------|--------|
| MINUS semantics | negation/* | Fixed: 3/12 → 9/12 after rewrite using Jena's `QueryIterMinus` pattern |
| EXISTS variable binding | Positive EXISTS 2 | Missing variable projection in EXISTS subquery |
| GRAPH in EXISTS | outer GRAPH in MINUS | GRAPH operator interaction with MINUS disjointness |

---

## 2. Jena Architecture Overview

### 2.1 Processing Pipeline

```
SPARQL text
    ↓  (Parser)
Query AST (syntax tree)
    ↓  (AlgebraGenerator — jena-arq/algebra/AlgebraGenerator.java, 618 lines)
Op tree (algebra)
    ↓  (Optimizer — jena-arq/algebra/optimize/)
Optimized Op tree
    ↓  (OpExecutor — jena-arq/engine/main/OpExecutor.java, 496 lines)
QueryIterator chain (streaming results)
    ↓  (ResultSet construction)
Bindings → output format
```

### 2.2 Our Pipeline (for comparison)

```
SPARQL text
    ↓  (Jena Sidecar — external Java process)
JSON algebra (serialized Op tree)
    ↓  (jena_ast_mapper.py — 740 lines)
Python Op types (jena_types.py — 445 lines)
    ↓  Pass 1: (jena_sql_collect.py — 408 lines)
RelationPlan IR
    ↓  Pass 2: (jena_sql_resolve.py — 158 lines)
Resolved RelationPlan
    ↓  Pass 3: (jena_sql_emit.py — 2,693 lines) ← THE MONOLITH
SQL string
    ↓  (PostgreSQL execution)
Result rows → SparqlResults
```

### 2.3 Key Architectural Difference

Jena processes each Op node **independently** via the Visitor pattern (`ExecutionDispatch`).
Each op type has its own `QueryIter*` class. The Visitor dispatches to `OpExecutor.execute(OpXxx)`,
which returns a `QueryIterator`.

Our pipeline flattens everything into one giant `emit()` function with `if plan.kind == "..."` branches.
This is why `jena_sql_emit.py` is 2,693 lines — it's doing the work of ~20 separate classes.

---

## 3. Review Areas

### 3.1 Datatype Flow — The NodeValue System

**Jena source**: `jena-arq/src/main/java/org/apache/jena/sparql/expr/`

The core insight: Jena's `NodeValue` is a **typed value object** that carries its XSD datatype
everywhere. Every expression evaluation produces a `NodeValue` with the correct type. There is
no separate "companion column" mechanism — the type is intrinsic to the value.

#### Key files to study:

| File | Lines | What it teaches us |
|------|-------|--------------------|
| `NodeValue.java` | 642 | Base class. Constants like `nvZERO`, `nvEmptyString`. Factory methods `makeInteger()`, `makeDecimal()`, `makeDouble()`, `makeString()`. Each carries its XSD type. |
| `ValueSpace.java` | 181 | Enum: VSPACE_NUM, VSPACE_STRING, VSPACE_LANG, VSPACE_BOOLEAN, VSPACE_DATETIME. All numeric subtypes collapse to `VSPACE_NUM`. This is why our comparator needed `__NUMERIC__` normalization. |
| `nodevalue/XSDFuncOp.java` | 1792 | **THE critical file.** All arithmetic ops, string ops, date ops. Type promotion via `classifyNumeric()`: integer < decimal < float < double. `calcReturn()` preserves lang+datatype from input. |
| `nodevalue/NodeFunctions.java` | 629 | RDF-level functions: `str()`, `lang()`, `datatype()`, `iri()`. `iri()` resolves against base URI. |
| `nodevalue/NodeValueOps.java` | ~200 | Argument validation: `checkAndGetStringLiteral()`, `checkTwoArgumentStringLiterals()`. Throws `ExprEvalException` on type mismatch. |

#### Specific lessons for our pipeline:

1. **`classifyNumeric(nv1, nv2)`** (XSDFuncOp.java:927-970):
   Type promotion is a 2D lookup:
   ```
   int + int → int       int + decimal → decimal
   int + float → float   int + double → double
   decimal + float → float  decimal + double → double
   float + double → double
   ```
   **Our bug**: We hardcode aggregate datatypes. We need a `_promote_numeric_type(left, right)` helper.

2. **`calcReturn(result, inputNode)`** (XSDFuncOp.java:752-754):
   ```java
   Node n2 = NodeFactory.createLiteral(result, arg.getLiteralLanguage(),
                                        arg.getLiteralBaseDirection(),
                                        arg.getLiteralDatatype());
   ```
   Copies language AND datatype from the input node to the output.
   **Our bug**: `_infer_extend_datatype` for STRAFTER/STRBEFORE/LCASE/UCASE uses a static
   CASE expression. It should reference the input variable's `__lang` and `__datatype` columns
   dynamically — which we partially do, but need to verify correctness per-row.

3. **`numDivide` for AVG** (XSDFuncOp.java:133-155):
   Integer division returns **decimal** (not integer). Float division returns float.
   Double division returns double.
   **Our bug**: AVG always returns `xsd:decimal` but should return `xsd:double` when inputs are doubles.

4. **Error propagation** — `ExprEvalException`:
   When a function receives wrong types, it throws `ExprEvalException`. The caller
   (`AccumulatorExpr.accumulate`) catches this and increments `errorCount`. If `errorCount > 0`,
   the aggregate returns NULL.
   **Our bug**: SQL doesn't have exception-based error propagation. We need to guard STRDT/STRLANG
   with CASE expressions that return NULL when the input has a lang tag (for STRDT) or a datatype
   (for STRLANG).

### 3.2 Aggregate Execution — QueryIterGroup

**Jena source**: `jena-arq/.../engine/iterator/QueryIterGroup.java` (182 lines)

This file shows the complete GROUP BY + aggregate algorithm:

#### Phase 1: Group and Accumulate (lines 112-135)
```java
while (iter.hasNext()) {
    Binding b = iter.nextBinding();
    Binding key = genKey(groupVarExpr, b, execCxt);  // evaluate GROUP BY exprs
    if (!accumulators.containsKey(key)) {
        for (ExprAggregator agg : aggregators) {
            Accumulator x = agg.getAggregator().createAccumulator();
            accumulators.put(key, Pair.create(v, x));
        }
    }
    for (Pair<Var, Accumulator> pair : accumulators.get(key))
        pair.getRight().accumulate(b, execCxt);  // feed row to each agg
}
```

#### Phase 2: Extract Results (lines 145-158)
```java
for (Binding k : accumulators.keySet()) {
    BindingBuilder builder2 = Binding.builder(k);  // start with GROUP BY key
    for (Pair<Var, Accumulator> pair : accs) {
        NodeValue value = pair.getRight().getValue();
        if (value == null) continue;  // error or no input → unbound
        builder2.add(v, value.asNode());
    }
    results.add(builder2.build());
}
```

#### Empty Group Handling (lines 87-108)
```java
if (noInput) {
    if (hasGroupBy) return nullIterator();  // GROUP BY with no input → 0 rows
    // No GROUP BY → one row with defaults
    for (ExprAggregator agg : aggregators) {
        Node value = agg.getAggregator().getValueEmpty();  // e.g., COUNT→0, AVG→0
        if (value == null) continue;
        builder.add(v, value);
    }
}
```

#### Lessons for our pipeline:

1. **`genKey()` evaluates GROUP BY expressions** — for `GROUP BY (DATATYPE(?o) AS ?d)`,
   the expression is evaluated per-row and the result becomes the key binding.
   **Our bug**: We try to project `d` from the inner query but it doesn't exist as a column.
   Need to compute the GROUP BY expression in the inner query and include it as a projected column.

2. **`getValueEmpty()`** per aggregate type:
   - COUNT → `NodeValue.nvZERO` (integer 0)
   - AVG → `NodeValue.nvZERO` (integer 0)
   - SUM → `NodeValue.nvZERO` (integer 0)
   - MIN/MAX → null (unbound)
   **Our bug**: PostgreSQL `AVG(...)` over empty group returns NULL, not 0.
   Need to wrap: `COALESCE(AVG(...), 0)` for the empty-group case.

3. **Error handling in accumulators**: `AccumulatorExpr.getValue()` returns NULL if
   `errorCount > 0`, meaning ANY error during accumulation makes the entire aggregate unbound.
   **Our bug**: PostgreSQL's AVG ignores NULLs; it doesn't track "error" rows separately.

### 3.3 Individual Aggregate Implementations

**Jena source**: `jena-arq/.../expr/aggregate/`

| File | Lines | Result Type Logic |
|------|-------|-------------------|
| `AggCount.java` | ~70 | Always `xsd:integer`. `getValueEmpty() = nvZERO`. |
| `AggAvg.java` | 118 | Accumulates via `numAdd`, divides via `numDivide`. Empty→`nvZERO`. Error in any row→null. Result type = `numDivide(total, count)` which is decimal for int inputs, double for double inputs. |
| `AggSum.java` | ~80 | Accumulates via `numAdd`. Type follows promotion rules. Empty→`nvZERO`. |
| `AggMin.java` / `AggMax.java` | ~50 each | Uses `NodeValue.compareAlways()`. Preserves input type exactly. Empty→null. |
| `AggGroupConcat.java` | ~130 | String concatenation with separator. Always `xsd:string`. |
| `AggSample.java` | ~70 | Returns first non-error value. Preserves type exactly. |

### 3.4 SPARQL Algebra → Execution Dispatch

**Jena source**: `jena-arq/.../engine/main/`

| File | Lines | Role |
|------|-------|------|
| `OpExecutor.java` | 496 | **The main dispatcher.** One `execute()` method per Op type. Each returns `QueryIterator`. |
| `ExecutionDispatch.java` | 324 | Visitor pattern bridge. `op.visit(this)` → `opExecutor.execute(op, input)`. Uses a stack for input/output iterators. |
| `JoinClassifier.java` | ~300 | Determines whether a join can be linear (pipeline) vs. needs hash join. |
| `LeftJoinClassifier.java` | ~150 | Same for OPTIONAL. |
| `VarFinder.java` | ~500 | **Critical for scoping.** Computes visible/fixed/optional/filter vars per Op. Used for join ordering, filter placement, MINUS commonVars. |
| `StageGenerator.java` | ~50 | Interface for BGP execution. TDB2 provides its own implementation. |

#### Key patterns in OpExecutor:

```java
// JOIN: execute left, then right independently, combine
protected QueryIterator execute(OpJoin opJoin, QueryIterator input) {
    QueryIterator left = exec(opJoin.getLeft(), input);
    QueryIterator right = exec(opJoin.getRight(), root());
    return Join.join(left, right, execCxt);
}

// LEFT JOIN (OPTIONAL): similar but with leftJoin + optional filter exprs
protected QueryIterator execute(OpLeftJoin opLeftJoin, QueryIterator input) {
    QueryIterator left = exec(opLeftJoin.getLeft(), input);
    QueryIterator right = exec(opLeftJoin.getRight(), root());
    return Join.leftJoin(left, right, opLeftJoin.getExprs(), execCxt);
}

// MINUS: execute both, compute common vars, filter with NOT EXISTS
protected QueryIterator execute(OpMinus opMinus, QueryIterator input) {
    QueryIterator left = exec(lhsOp, input);
    QueryIterator right = exec(rhsOp, root());
    Set<Var> commonVars = OpVars.visibleVars(lhsOp);
    commonVars.retainAll(OpVars.visibleVars(rhsOp));
    return QueryIterMinus.create(left, right, commonVars, execCxt);
}

// GROUP BY: execute sub-op, then group
protected QueryIterator execute(OpGroup opGroup, QueryIterator input) {
    QueryIterator qIter = exec(opGroup.getSubOp(), input);
    return new QueryIterGroup(qIter, opGroup.getGroupVars(),
                              opGroup.getAggregators(), execCxt);
}

// EXTEND (BIND): execute sub-op, then add computed variable
protected QueryIterator execute(OpExtend opExtend, QueryIterator input) {
    QueryIterator qIter = exec(opExtend.getSubOp(), input);
    return new QueryIterAssign(qIter, opExtend.getVarExprList(), execCxt, true);
}
```

**Critical lesson**: EXTEND evaluates AFTER its sub-op. The sub-op's variables are visible
to the EXTEND expression, but the EXTEND variable is NOT visible inside the sub-op.
This is the BIND scoping rule that our `bind03/04/07` tests fail on.

### 3.5 TDB2 — Storage-Level Execution

**Jena source**: `jena-tdb2/src/main/java/org/apache/jena/tdb2/solver/`

| File | Lines | What it teaches |
|------|-------|-----------------|
| `OpExecutorTDB2.java` | 400 | Overrides only BGP and Filter execution. Everything else delegates to parent `OpExecutor`. This means JOIN, MINUS, UNION, GROUP BY are **storage-independent** — they work on bindings, not raw data. |
| `SolverLibTDB.java` | ~300 | Triple pattern → index lookup. Uses `NodeId` (analogous to our `term_uuid`) internally. Only resolves to `Node` at output. |
| `PatternMatchTDB2.java` | ~160 | Dispatches to tuple index based on graph node. |
| `BindingTDB.java` | ~130 | Lazy binding: stores `NodeId`, resolves to `Node` on demand. Validates our inner/outer query pattern. |

**Key insight**: TDB2 only customizes BGP execution (index lookups). All higher-level ops
(joins, filters, groups, extends, minus) use the generic ARQ implementations. This validates
that our approach of using PostgreSQL for storage (BGP execution) and implementing higher-level
ops in SQL is architecturally sound.

### 3.6 Expression Evaluation — Function Dispatch

**Jena source**: `jena-arq/.../sparql/expr/`

The expression class hierarchy:
```
Expr (abstract)
├── ExprVar           — variable reference
├── ExprNode          
│   └── NodeValue     — constant value (typed)
│       ├── NodeValueInteger
│       ├── NodeValueDecimal
│       ├── NodeValueDouble
│       ├── NodeValueString
│       ├── NodeValueBoolean
│       └── NodeValueDT (datetime)
├── ExprFunction      — function call
│   ├── ExprFunction0 — NOW(), STRUUID()
│   ├── ExprFunction1 — STR(), LANG(), DATATYPE(), ABS(), STRLEN()
│   ├── ExprFunction2 — CONTAINS(), STRSTARTS(), =, <, +, -
│   ├── ExprFunction3 — IF(), SUBSTR()
│   └── ExprFunctionN — CONCAT(), COALESCE()
├── ExprFunctionOp    — EXISTS(), NOT EXISTS()
└── ExprAggregator    — COUNT(), AVG(), etc.
```

Each `ExprFunction` subclass has an `eval()` method that:
1. Evaluates arguments (calling `eval()` recursively)
2. Performs the operation
3. Returns a `NodeValue` with the correct type

**Special methods**:
- `evalSpecial(Binding, FunctionEnv)` — for short-circuit evaluation (IF, logical AND/OR)
  and access to environment (IRI base resolution)

#### Lessons:

1. **IF uses `evalSpecial`** — only evaluates the chosen branch (lines 55-61 of `E_If.java`).
   SQL `CASE WHEN` evaluates all branches. This matters when a branch would error.

2. **IRI stores `parserBase`** at parse time (line 49 of `E_IRI.java`). The base URI is
   captured when the expression is created, not when it's evaluated. Our sidecar's algebra
   JSON doesn't include this base URI.

3. **Error handling is exception-based**: Functions throw `ExprEvalException` on type errors.
   The evaluation framework catches these and treats the result as "unbound". In SQL, we
   need CASE guards for every function that can error.

---

## 4. Code Organization Lessons

### 4.1 Jena's Decomposition

Jena splits what we have in one file across ~20 focused classes:

| Jena Class | Lines | Our Equivalent | Our Lines |
|------------|-------|----------------|-----------|
| `OpExecutor.execute(OpBGP)` | ~30 | `_emit_bgp()` | ~100 |
| `OpExecutor.execute(OpJoin)` | ~10 | `_emit_join()` | ~90 |
| `OpExecutor.execute(OpLeftJoin)` | ~10 | (inside `_emit_join`) | ~40 |
| `OpExecutor.execute(OpUnion)` | ~10 | `_emit_union()` | ~30 |
| `OpExecutor.execute(OpMinus)` | ~15 | `_emit_minus()` | ~65 |
| `OpExecutor.execute(OpFilter)` | ~20 | (inside `emit()`) | ~50 |
| `OpExecutor.execute(OpGroup)` | ~5 | `_emit_bgp_aggregate()` | ~150 |
| `OpExecutor.execute(OpExtend)` | ~5 | (inside `emit()`) | ~100 |
| `OpExecutor.execute(OpProject)` | ~15 | (inside `emit()`) | ~100 |
| `OpExecutor.execute(OpOrder)` | ~5 | (inside `emit()`) | ~20 |
| `OpExecutor.execute(OpSlice)` | ~5 | (inside `emit()`) | ~10 |
| `QueryIterGroup` | 182 | `_emit_bgp_aggregate()` | ~150 |
| `QueryIterMinus` | 96 | `_emit_minus()` | ~65 |
| `QueryIterFilterExpr` | ~70 | (inline in emit) | ~50 |
| `QueryIterAssign` (EXTEND) | ~100 | (inline in emit) | ~100 |
| `XSDFuncOp` (arithmetic) | 1792 | `jena_sql_expressions.py` | 782 |
| `VarFinder` | ~500 | `_plan_vars()` | ~10 |
| `JoinClassifier` | ~300 | `_reorder_joins()` | ~165 |

### 4.2 Proposed Decomposition of `jena_sql_emit.py`

Split the 2,693-line monolith into focused modules:

```
jena_sql_emit.py (2,693 lines)
    ↓ split into ↓

jena_sql_emit.py          (~400)  — Main `emit()` dispatcher + Op routing
jena_sql_emit_bgp.py      (~500)  — _emit_bgp, _emit_bgp_optimized, _emit_bgp_aggregate
jena_sql_emit_join.py      (~200)  — _emit_join, _emit_union, _emit_minus
jena_sql_emit_extend.py    (~300)  — _resolve_extend_for_outer, _infer_extend_*
jena_sql_emit_aggregate.py (~300)  — _agg_expr_to_inner_sql, _having_expr_to_sql, agg companion cols
jena_sql_emit_path.py      (~200)  — _emit_path, _path_to_sql
jena_sql_emit_reorder.py   (~300)  — _reorder_joins, _apply_semijoin_pushdown, _build_staged_inner
jena_sql_emit_text.py      (~200)  — _extract_text_filters, _try_text_filter_to_constraint
jena_sql_emit_exists.py    (~100)  — _emit_exists_subquery
jena_sql_emit_table.py     (~100)  — _emit_table
```

Each module mirrors a Jena class's responsibility boundary:

| Our Module | Jena Equivalent |
|-----------|-----------------|
| `jena_sql_emit.py` (dispatcher) | `OpExecutor.java` + `ExecutionDispatch.java` |
| `jena_sql_emit_bgp.py` | `StageGeneratorGeneric` + TDB2's `PatternMatchTDB2` |
| `jena_sql_emit_join.py` | `Join.java`, `QueryIterMinus.java` |
| `jena_sql_emit_extend.py` | `QueryIterAssign.java` + type inference |
| `jena_sql_emit_aggregate.py` | `QueryIterGroup.java` + `AccumulatorExpr` subclasses |
| `jena_sql_emit_reorder.py` | `JoinClassifier.java` + TDB2's `ReorderTransformation` |
| `jena_sql_expressions.py` (existing) | `XSDFuncOp.java` + `NodeFunctions.java` |

---

## 5. Review Tasks (Ordered by Impact)

### Phase 1: Datatype Flow (directly fixes ~20 DAWG failures)

- [ ] **Task 1.1**: Study `XSDFuncOp.classifyNumeric()` — implement `_promote_numeric_type()` helper
  - Files: `XSDFuncOp.java:927-970`
  - Impact: Fixes aggregate datatype propagation for SUM/AVG/MIN/MAX
  
- [ ] **Task 1.2**: Study `XSDFuncOp.calcReturn()` — verify our STRAFTER/STRBEFORE/LCASE/UCASE companion columns
  - Files: `XSDFuncOp.java:752-755`, `strAfter:774-789`, `strLowerCase:791-796`
  - Impact: Fixes STRAFTER/STRBEFORE datatyping tests

- [ ] **Task 1.3**: Study `AggAvg.AccAvg.getAccValue()` — fix AVG result typing
  - Files: `AggAvg.java:107-115`
  - Impact: AVG of doubles should return double, not decimal

- [ ] **Task 1.4**: Study `AggAvg.getValueEmpty()` — fix empty group handling
  - Files: `AggAvg.java:47,56`, also `AggCount.java`, `AggSum.java`, `AggMin.java`, `AggMax.java`
  - Impact: Fixes "AVG with empty group" test

- [ ] **Task 1.5**: Study `AccumulatorExpr.getValue()` — understand error propagation in aggregates
  - Files: `AccumulatorExpr.java:77-82`
  - Impact: Fixes "Error in AVG" and "Protect from error in AVG" tests

- [ ] **Task 1.6**: Study `E_IRI.evalSpecial()` — understand base URI resolution
  - Files: `E_IRI.java:69-96`
  - Impact: Fixes IRI()/URI() test

- [ ] **Task 1.7**: Study `XSDFuncOp.strConcat()` — implement proper CONCAT type logic
  - Files: `XSDFuncOp.java:830-879`
  - Impact: Fixes CONCAT() 2 test

### Phase 2: Aggregate & GROUP BY Execution (fixes ~10 ERR tests)

- [ ] **Task 2.1**: Study `QueryIterGroup.genKey()` — fix GROUP BY with expressions
  - Files: `QueryIterGroup.java:164-180`
  - Impact: Fixes "GROUP BY with a built-in function" and "GROUP BY with a function"

- [ ] **Task 2.2**: Study `AggGroupConcat` — fix GROUP_CONCAT SQL generation
  - Files: `AggGroupConcat.java`
  - Impact: Fixes GROUP_CONCAT 2 test

- [ ] **Task 2.3**: Study `QueryIterGroup` empty group logic (lines 87-108)
  - Impact: Fixes "agg on empty set, explicit grouping", "COUNT: no match"

### Phase 3: BIND Scoping & Variable Visibility (fixes ~5 BIND tests)

- [ ] **Task 3.1**: Study `OpExtend` placement in algebra tree
  - Files: `algebra/op/OpExtend.java`, `AlgebraGenerator.java` (BIND handling)
  - Impact: Understanding where EXTEND goes relative to FILTER

- [ ] **Task 3.2**: Study `VarFinder` — visible, fixed, optional variable computation
  - Files: `engine/main/VarFinder.java`
  - Impact: Correct scoping for BIND variables in filters

- [ ] **Task 3.3**: Study `QueryIterAssign` — EXTEND execution semantics
  - Files: `engine/iterator/QueryIterAssign.java`
  - Impact: BIND03, BIND04, BIND07, BIND10, BIND11

### Phase 4: Code Decomposition (maintainability)

- [ ] **Task 4.1**: Extract `_emit_bgp*` functions into `jena_sql_emit_bgp.py`
- [ ] **Task 4.2**: Extract `_emit_join`, `_emit_union`, `_emit_minus` into `jena_sql_emit_join.py`
- [ ] **Task 4.3**: Extract `_infer_extend_*`, `_resolve_extend_for_outer` into `jena_sql_emit_extend.py`
- [ ] **Task 4.4**: Extract `_agg_expr_to_inner_sql`, `_having_expr_to_sql` into `jena_sql_emit_aggregate.py`
- [ ] **Task 4.5**: Extract `_reorder_joins`, `_build_staged_inner` into `jena_sql_emit_reorder.py`

---

## 6. Quick Reference: Jena Source Paths

All paths relative to `jena-main-source/jena-arq/src/main/java/org/apache/jena/sparql/`:

| Area | Path | Key Files |
|------|------|-----------|
| **Algebra ops** | `algebra/op/` | OpBGP, OpJoin, OpLeftJoin, OpUnion, OpMinus, OpFilter, OpExtend, OpGroup, OpProject, OpOrder, OpSlice |
| **Algebra compiler** | `algebra/` | AlgebraGenerator.java (SPARQL→algebra) |
| **Expression types** | `expr/` | E_IRI, E_If, E_Coalesce, E_StrConcat, E_StrAfter, etc. |
| **NodeValue types** | `expr/nodevalue/` | XSDFuncOp, NodeFunctions, NodeValueOps |
| **Aggregates** | `expr/aggregate/` | AggAvg, AggSum, AggCount, AggMin, AggMax, AggGroupConcat, AccumulatorExpr |
| **Execution dispatch** | `engine/main/` | OpExecutor, ExecutionDispatch, VarFinder, JoinClassifier |
| **Result iterators** | `engine/iterator/` | QueryIterGroup, QueryIterMinus, QueryIterAssign, QueryIterFilterExpr |
| **Variable scoping** | `engine/main/` | VarFinder.java (visible, fixed, optional vars per Op) |

TDB2 paths relative to `jena-main-source/jena-tdb2/src/main/java/org/apache/jena/tdb2/`:

| Area | Path | Key Files |
|------|------|-----------|
| **Query executor** | `solver/` | OpExecutorTDB2, SolverLibTDB, PatternMatchTDB2 |
| **Storage model** | `store/` | NodeId, NodeIdInline, TupleIndex |
| **Binding** | `solver/` | BindingTDB (lazy NodeId→Node resolution) |

---

## 7. Findings Log

Record discoveries here as the review progresses:

### 7.1 Already Discovered (from earlier review sessions)

| Finding | Source | Impact | Applied? |
|---------|--------|--------|----------|
| MINUS uses `commonVars` intersection, `containsCompatibleWithSharedDomain` | `QueryIterMinus.java`, `LinearIndex.java` | Rewrote `_emit_minus` from EXCEPT to NOT EXISTS | ✅ Applied: 3/12 → 9/12 negation tests |
| `ExprFunction3` not handled by mapper | `E_If.java` → `ExprFunction3` type | Added to `jena_ast_mapper.py` | ✅ Applied |
| `calcReturn()` propagates lang+datatype from input | `XSDFuncOp.java:752-754` | Validates our `_infer_extend_datatype` for STRAFTER/LCASE/etc. | ✅ Partially applied |
| `numDivide(int, int)` returns decimal | `XSDFuncOp.java:133-139` | AVG of integers should return decimal | ✅ Already correct |
| IF uses `evalSpecial` (short-circuit) | `E_If.java:55-61` | SQL CASE WHEN evaluates all branches | ⚠️ Known limitation |
| IRI stores `parserBase` at parse time | `E_IRI.java:49,56` | Sidecar doesn't pass base URI | ⚠️ Known limitation |
| AVG empty group → `nvZERO` | `AggAvg.java:47` | Need COALESCE wrapper | ❌ Not yet applied |
| CONCAT: all same lang→preserve, mixed→xsd:string | `XSDFuncOp.java:830-879` | Our CONCAT returns NULL datatype | ❌ Not yet applied |
| All numeric types collapse to VSPACE_NUM | `ValueSpace.java:71` | Added `__NUMERIC__` normalization to comparator | ✅ Applied |
| xsd:string = plain literal in RDF 1.1 | Standard | Added xsd:string stripping to executor + comparator | ✅ Applied |

### 7.2 New Findings (This Session)

| Finding | Source | Impact | Applied? |
|---------|--------|--------|----------|
| **QueryIterAssign (BIND)**: `accept()` evaluates expr against current binding snapshot. If expr returns null (error), variable is simply not added (unbound). If variable already exists with different value, entire row is dropped (`return null`). | `QueryIterAssign.java:60-91` | BIND error handling should produce unbound, not SQL error. BIND on already-bound var with different value should filter out the row. | ❌ Not yet applied |
| **VarFinder.visit(OpExtend)**: Visits sub-op FIRST, then adds BIND vars to `defines`. Confirms BIND vars are visible only after sub-op executes. | `VarFinder.java:340-343` | Validates that BIND vars can't be used in filters within the same scope level. Our SQL needs to ensure EXTEND columns aren't referenced in the inner subquery's WHERE. | ❌ Not yet applied |
| **VarFinder.visit(OpMinus)**: `mergeRightMask()` takes `defines` only from LEFT. Right side defines go to `filterMentions`. Output vars = left vars only. | `VarFinder.java:210-225` | Already applied in our MINUS rewrite (output = left vars). Validates the fix. | ✅ Already correct |
| **VarFinder.visit(OpFilter)**: Visits sub-op first, then processes filter exprs. Filter vars go to `filterMentions`/`filterMentionsOnly`. | `VarFinder.java:328-331` | Filter can reference vars from sub-op but not from sibling EXTEND. | ⚠️ Informs BIND scoping fixes |
| **VarFinder.isLikelyToBeDefined()**: Heuristic for whether EXTEND var is always defined (constant, all args defined) vs optionally defined (references optional var). COALESCE is special-cased (any arg defined → likely defined). | `VarFinder.java:365-384` | EXTEND vars can be `optDefines` not `defines` if their expression references optional vars. This affects join classification. | ⚠️ Informational |
| **AggSum accumulation**: Uses `numAdd(nv, total)` which promotes types via `classifyNumeric`. First value sets the initial type; subsequent values may promote it. Empty → `nvZERO` (integer 0). | `AggSum.java:73-83` | SUM type follows promotion rules across all accumulated values. Our SQL SUM always returns the PostgreSQL type (usually numeric). | ❌ Type mismatch for SUM results |
| **AggMax/Min**: Uses `compareAlways(maxSoFar, nv)`. Preserves the actual NodeValue of the max/min element. Empty → null (unbound). | `AggMaxBase.java:56-69` | MAX/MIN preserve the exact input type. Our SQL MAX/MIN preserves PostgreSQL type but we hardcode `xsd:decimal` as companion datatype. | ❌ Type mismatch for MAX/MIN results |
| **AccumulatorExpr error handling**: ANY error during accumulation (non-numeric input to AVG/SUM, type mismatch) sets `errorCount++`. If `errorCount > 0`, `getValue()` returns null, making the entire aggregate unbound. | `AccumulatorExpr.java:60-69,77-82` | PostgreSQL aggregates silently skip NULLs but don't track errors. We need to detect and propagate error conditions for "Error in AVG" test. | ❌ Not yet applied |

---

## 8. Design: SPARQL→SQL Variable Name Mapping

### Problem

Currently, SPARQL variable names are used directly as SQL column aliases. This causes:

1. **Case corruption**: PostgreSQL lowercases unquoted identifiers. SPARQL `?C` → SQL `C__type`
   → PostgreSQL returns `c__type` → executor can't find `C__type`.
2. **Collision risk**: SPARQL vars like `?type` or `?order` can clash with SQL reserved words.
3. **No separation of concerns**: The executor reverse-engineers variable names from
   PostgreSQL column names instead of having an authoritative mapping.

### Proposed Design

```
                     SPARQL layer              SQL layer              Result layer
                     ──────────               ──────────             ────────────
Variable names:      ?C, ?s, ?avg             v0, v1, v2             C, s, avg
Companion cols:                               v0__type, v0__uuid     (stripped)
                                              v1__type, v1__uuid
Mapping:             var_map = {v0: "C", v1: "s", v2: "avg"}
```

**SQL column naming convention**: `v{N}` where N is a globally sequential counter from
`AliasGenerator`. All lowercase, no quoting needed, no PostgreSQL reserved word conflicts.

**Companion columns**: `v{N}__type`, `v{N}__uuid`, `v{N}__lang`, `v{N}__datatype`, `v{N}__num`.
All lowercase, consistent naming.

### Implementation Plan

**Phase A: Add `var_map` to the pipeline**

1. **`AliasGenerator`** (`jena_sql_ir.py`): Add `next_var(sparql_name: str) -> str` method
   that returns `v{N}` and records `{v{N}: sparql_name}` in a `var_map: Dict[str, str]`.

2. **`generate_sql()`** (`jena_sql_generator.py`): Return `(sql_str, var_map)` tuple instead
   of just `sql_str`. The var_map comes from `aliases.var_map` after the 3-pass pipeline.

3. **`QueryResult`** (`jena_sparql_orchestrator.py`): Add `sparql_vars: List[str]` field
   (the original SPARQL variable names in projection order) and `var_map: Dict[str, str]`.

4. **Orchestrator `execute()`**: Thread var_map from `generate_sql()` into `QueryResult`.

**Phase B: Update emitter to use opaque names**

5. **`_emit_bgp_optimized()`** and `emit()`**: When projecting a SPARQL variable, use
   `aliases.next_var(sparql_name)` to get the SQL alias. Store the mapping.

6. **Companion columns**: Use `{sql_alias}__type` etc. instead of `{sparql_name}__type`.

**Phase C: Update executor to use var_map**

7. **`dawg_sql_executor.py`**: Instead of extracting variable names from `result.columns`,
   use `result.sparql_vars`. For each SPARQL var, look up its SQL alias via the inverse
   var_map and read from `row[sql_alias]`, `row[f"{sql_alias}__type"]`, etc.

8. **Remove the ad-hoc lowercase fallback** in `_infer_binding()`.

### Benefits

- **Correctness**: No case corruption, no reserved word conflicts.
- **Debuggability**: `var_map` makes the SPARQL↔SQL relationship explicit and inspectable.
- **Extensibility**: Internal SQL rewrites (CTE refs, subquery flattening) can safely rename
  columns without worrying about SPARQL name preservation.
- **Jena parallel**: This mirrors Jena's `Var` objects which carry the original name through
  all algebra transformations, separate from the execution engine's internal representation.

### Migration

This is a **cross-cutting refactor** that touches:
- `jena_sql_ir.py` (AliasGenerator)
- `jena_sql_generator.py` (return type)
- `jena_sql_emit.py` (column aliases in all projection sites)
- `jena_sparql_orchestrator.py` (QueryResult, execute)
- `dawg_sql_executor.py` (result mapping)
- Any test that inspects generated SQL column names

Recommend doing this as a **dedicated PR** after the current DAWG pass-rate push stabilizes.

---

## 9. Next Steps

1. Continue Phase 1 aggregate/datatype fixes — immediate DAWG pass-rate impact
2. After stabilizing at ~70%, implement the var_map refactor (Section 8)
3. Phase 2 (GROUP BY, BIND scoping) fixes based on updated failure patterns
4. Phase 4 (code decomposition) can proceed in parallel
