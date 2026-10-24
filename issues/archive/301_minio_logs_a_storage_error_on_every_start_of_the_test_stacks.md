# 301 — MinIO logs a storage error on every start of the test stacks

## Status: FIXED 2026-10-24 — both stacks' `minio` serves from `/data/store`; verified on the vg test stack

The cause is that the image ships `/data/.minio.sys` in one of its layers.
See **Fix (applied)** and **Verified** below.

**Related:** `docker-compose.test.yml` (the `minio` service and its note on why
the image is `chainguard/minio:latest`), `docker-compose.planner.yml` (same
service, copied).

## Found

While reading the planner stack's container logs. Each start of a MinIO
container with no volume on `/data` logs this, with a stack trace:

```
API: SYSTEM.storage
Error: unable to rename (/data/.minio.sys/tmp -> /data/.minio.sys/tmp-old/<uuid>)
Rename across devices not allowed, please fix your backend configuration ...
drive may be faulty, please investigate (*fmt.wrapError)
       ...
       5: .../cmd/prepare-storage.go:89:cmd.bgFormatErasureCleanupTmp()
```

That happens on `vitalgraph-test-minio` (3 occurrences in its log, one per start
since 2026-10-06) and `vitalgraph-planner-minio`. The dev stack's
`vitalgraph-minio` has a named volume and logs none.

## Cause

`/data` sits on the container's overlay root filesystem. At startup MinIO
renames its `.minio.sys/tmp` directory aside to clean it
(`bgFormatErasureCleanupTmp`). overlayfs refuses that directory rename with
`EXDEV`, which MinIO reports as a cross-device rename and a possibly faulty
drive.

**Why overlay refuses it (confirmed 2026-10-24):** overlayfs refuses to rename
only directories that come from an *image layer*. A directory created at
runtime in the container's writable layer renames fine. The chainguard image
ships a pre-made, empty `/data/.minio.sys/` (`buckets`, `config`, `multipart`,
`tmp/.trash`, `tmp-old`) in its layers, so `tmp` is a lower-layer directory.
Checked with `os.rename` in a `python:3-alpine` container: an upper-layer
directory renames, and a lower-layer one gets `[Errno 18] Cross-device link`.
(Busybox/coreutils `mv` hides this because it falls back to copy+delete.)
The failed rename leaves `tmp` in the lower layer, so the error comes back on
every restart, not only on the first start.

That is also why both repro rows below are clean. An anonymous volume is a real
filesystem: Docker copies the image's `.minio.sys` into it, and a directory
there renames normally. A tmpfs starts empty.

Reproduced with throwaway containers of the same image, `server /data`, 6 s
after start:

| `/data` | rename errors | API up |
|---|---|---|
| container root (as in both test stacks) | 1 | yes |
| anonymous volume (`-v /data`) | 0 | yes |
| tmpfs (`--tmpfs /data`) | 0 | yes |

## Impact

- **Functional: none observed.** MinIO formats its drive and serves the API
  after the error, and the stacks' storage tests run.
- **The cleanup it attempted does not happen.** Stale files left in
  `.minio.sys/tmp` from an interrupted upload are not removed. On an ephemeral
  test stack that is bounded by the container's life.
- **Log noise that reads as a fault.** It is an `Error` with a stack trace that
  says "drive may be faulty", printed on every start, and it was the first thing
  asked about when reading the logs. Noise like that trains people to skip past
  real errors.

## Fix (applied): serve from a subdirectory the image does not ship

```yaml
    command: server /data/store --console-address ":9001"
```

The `minio` service in `docker-compose.test.yml` now runs this command, with a
comment giving the reason and why tmpfs was not used. `docker-compose.planner.yml`
has the same change. That file is gitignored (`**/*.yml`), so the change is
local, and `vitalgraph-planner-minio` only picks it up on its next recreate. It
was left running because the planner stack was in use.

`/data` is mode 777 in the image, so the nonroot (65532) server creates
`/data/store` in the writable layer, and every directory under it renames
normally. Throwaway containers, start + `docker restart`, 6 s each:

| `server` path | rename errors (2 starts) | API up |
|---|---|---|
| `/data` (as now) | 2 | yes |
| `/data/store` | 0 | yes |

The lifetime stays exactly as it is now: objects survive a stop/start and are
dropped when the container is recreated. Nothing extra goes into memory, and
nothing is orphaned.

## Verified (2026-10-24, vg test stack)

- Brought up with `docker-compose.test.yml` + `docker-compose.test.persist.yml`.
  `vitalgraph-test-minio` was recreated with the new command, and postgres kept
  its persisted data.
- MinIO log: **0** `Rename across devices` lines after the first start, and 0
  after a `docker restart` (2 `API:` lines, so it started twice). Before the
  fix there was one error per start.
- `/data/store/vitalgraph-files` is created at runtime: the app makes the bucket
  on first use.
- `tests/api/test_files_api.py` + `test_kgdocuments_api.py` on :8002:
  **31 passed**.
- The app image was not rebuilt for that first run. The change is MinIO's
  compose config only, and no application code is under test.
- Re-run on the rebuilt stack (app recreated 10:53). MinIO was carried over and
  started a third time on `/data/store`: **0** rename errors across all 3
  starts. Files + kgdocuments API tests: **31 passed**, and still 0 errors
  afterwards.

Side effect: the recreate dropped the old container and its 214 MB of objects
in `/data`. Those were test uploads left behind by earlier runs. Any persisted
file or document node from before 2026-10-24 now points at a missing object.
A recreate always did that.

## Why not tmpfs (the first proposal)

The tmpfs proposal below fixes the log, but it changes two things that the
"ephemeral" framing hid:

- **Objects would be lost on stop/start, not only on recreate.**
  `vitalgraph-test-minio` was created 2026-10-05 and has been restarted since,
  not recreated. Its `/data` holds the 214 MB `vitalgraph-files` bucket (140
  objects). Under the persist override the test postgres keeps its data across
  restarts, and with tmpfs MinIO would not. Every persisted
  `urn_kgdocument_*_source` / file node would then point at an object that is
  gone.
- **Leaked test objects would sit in RAM.** The API tests do not delete what
  they upload: there are 20 copies of each `apitest_files_*` object and of each
  `upload_*_source` document, plus 2.4 MB `apitest_wrappers_*` objects. That is
  about 10 MB per suite run, and it accumulates until the container stops. On
  this Mac, memory pressure has already corrupted measurements once (issues/289).

Test-object cleanup is a separate gap and is not filed.

### Original proposal (superseded)

Give the two test stacks' `minio` service a `tmpfs` on `/data`:

```yaml
    tmpfs:
      - /data
```

tmpfs keeps the property the test stack documents ("No volumes — ephemeral
storage"): the data still vanishes with the container, and nothing is left
behind. An anonymous volume would orphan itself on every recreate, the way the
test postgres's anonymous PGDATA volume does (see `docker-compose.test.yml`).
The cost is memory, which is small for test objects. Don't use tmpfs for a large
document-import test without checking that.

Verify: recreate the service and check that its log has no `Rename across
devices` line and that `tests/api`'s storage cases pass.
