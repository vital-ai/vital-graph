# CI Restores Locally-Built Wheels Across Runners, And They SIGILL

## Status: FIXED 2026-09-11 in `.github/workflows/{unit-tests,e2e-tests}.yml`.
## Written up because the SYMPTOM is maximally misleading and the next one will
## look just as much like a code defect as this one did.

**Raised:** 2026-09-11, when `Tests (Tier 1 + 2)` started failing on a
**docs-only commit** that touched nothing but `issues/*.md`.

## The symptom

    Fatal Python error: Illegal instruction        (exit code 132 = SIGILL)
    Current thread (most recent call first):
      File "<frozen importlib._bootstrap_external>", line 1293 in create_module
      File ".../vital_ai_vitalsigns/collection/vector_collection_impl.py"
      ...
      File "tests/unit/test_client_retry.py", line 84 in make_client

Not a test failure. A hard crash, reproducible on rerun, while LOADING a C
extension — `create_module` is the import machinery instantiating a native
module. `vector_collection_impl` imports `hnswlib`.

## The cause

`hnswlib` publishes an sdist, not wheels for every platform, so **pip compiles
it at install time** and caches the result in `~/.cache/pip/wheels`.

The workflow cached all of `~/.cache/pip`:

```yaml
key: ${{ runner.os }}-pip-${{ matrix.python-version }}-${{ hashFiles('pyproject.toml') }}
restore-keys: |
  ${{ runner.os }}-pip-${{ matrix.python-version }}-
```

`restore-keys` is a **PREFIX** match. So when the exact key misses, the job
restores an older cache — including a wheel **compiled on a different runner**.
GitHub runners differ in CPU, and the binary then executes an instruction the
host does not support.

## Why it was hard to read

Every confusing part follows from that, and each one argued AGAINST looking at
the cache:

* **It started on a docs-only commit.** Editing `pyproject.toml` (twice, while
  investigating) changed the exact cache key, so the job fell back to the prefix
  and picked up the incompatible wheel. The trigger was the investigation.
* **It passed locally.** Built for this CPU.
* **It hit an unrelated dependabot branch an hour earlier.** Shared cache, not a
  shared code change — which is what (correctly) ruled out the commits, and
  (incorrectly) suggested a dependency version.
* **No new release was involved.** `hnswlib` 0.8.0 is from **2023**. Every
  attempt to bisect by version was searching a space that did not contain the
  answer.

## Two wrong fixes first, and why

**`datasketch`** — a real and separate defect: `datasketch>=1.9.0,<2.0` was
declared only in the `server` extra, while `vital-ai-vitalsigns` (a CORE
dependency) requires `datasketch>=1.6.5` unbounded. **A bound in an extra cannot
constrain a transitive dependency of a core one**, so CI resolved 2.0.0. Worth
fixing, and kept — but it was never this crash.

**`torch<2.14`** — a hypothesis, with CI as the experiment. Falsified: torch
resolved to 2.13.0 and the crash was byte-identical. Reverted, because a bound
left in place would permanently misattribute the cause to a package that is
fine.

Both came from the same mistake: treating "a new version appeared" as the
explanation without reading the crash frames. **The frames named the module and
the import machinery.** One grep at `vector_collection_impl` would have found
`import hnswlib` before either guess.

## The fix

Drop only the built wheels after restore, keeping the download cache:

```yaml
- name: Drop locally-built wheels from the restored cache
  run: rm -rf ~/.cache/pip/wheels
```

`restore-keys` stays — it is useful, and the download cache is
machine-independent. What must not cross runners is a binary this machine
compiled.

## The pattern to recognise

**Any sdist-only dependency has this exposure**, not just `hnswlib`. Removing
`wheels/` covers them all, so no further action is needed today. But if a
`SIGILL`, `SIGSEGV` or `Illegal instruction` ever appears in CI again:

1. **Read the crash frames before the dependency list.** `create_module` in the
   traceback means a native module failed to LOAD, and the frame above it names
   which package pulled it in.
2. **A crash on a commit that changed no code is an environment fact**, not a
   code fact. Ask what the environment restored, not what the diff contains.
3. **Check whether the package builds from source** (`pip download --no-binary`
   or simply the absence of a matching wheel on PyPI). If it does, a cached
   build is machine-specific.
4. **Version-bisect last.** It is the slowest check and it only works if a new
   release is actually involved.
