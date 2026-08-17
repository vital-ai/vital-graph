"""Marks `scripts/` as a real package.

Without this it is a NAMESPACE package, and `tests/unit/test_perf_baseline_stamping`
inserts `<repo>/scripts` at `sys.path[0]` so it can `import perf_compare` directly.
That binds the name `scripts` to a namespace rooted INSIDE this directory, and
every later `from scripts.X import ...` looks for `scripts/scripts/X.py` and fails
with ModuleNotFoundError.

The effect was order-dependent and therefore invisible in isolation: five paging
tests passed when their files were run alone and failed in a full-suite run, which
is also how they came to be blamed on an unrelated change (issues/088).
"""
