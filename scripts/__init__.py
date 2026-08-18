"""Marks `scripts/` as a real package, so `from scripts.X import ...` is
unambiguous wherever it appears.

As a NAMESPACE package it was ambiguous, and one `sys.path.insert(0, "<repo>/
scripts")` in a test was enough to break it: that binds the name `scripts` to a
namespace rooted INSIDE this directory, so every later `from scripts.X import ...`
looks for `scripts/scripts/X.py` and raises ModuleNotFoundError.

The effect was order-dependent and therefore invisible in isolation — five paging
tests passed when their own files ran and failed in a full-suite run, and were
briefly blamed on an unrelated change (issues/088).

The insert has since been removed as well, so this is defence in depth rather
than the fix. It also makes the double-import hazard go away by construction:
with a path inserted, `perf_compare` and `scripts.perf_compare` are two module
objects with separate state, and a cache in one is invisible to the other.
"""
