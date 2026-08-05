# Test-Stack Data Accumulates Across Rebuilds; Registry Tombstones Unbounded

## Status: OPEN

## Summary

The test stack is *designed* to start with an empty database — `docker-compose.test.yml:68`
says so on the postgres service:

```yaml
    # No volumes — starts empty every time
```

It does not, in practice. Data survives indefinitely across `--build` cycles,
and some of it grows without bound. Measured on the local test stack after one
working session:

| Data | Count | Growth |
|---|---|---|
| Entity-registry **soft-delete tombstones** | **426** (vs 2 live rows) | ~3 per spec run, forever |
| Duplicate seeded `E2E Registry Person` | 2 | ~~+1 per seed run~~ — **fixed**, see item 3 |
| Orphaned FileNodes (before the fix in issues/022) | 103 | +4 per run |
| Stale spaces (`apitest_*`, `probe_*`) | 2 | +1 per API-suite run |

This is not cosmetic. Every "flake" traced in `issues/022` that turned out to be
accumulated residue — the Files list pushing its own fixture off page 1, the
registry duplicate tripping Playwright strict mode, `apitest_*` sorting ahead of
`e2e_*` and becoming the default space selection that exposed the `Indexes.tsx`
race — was caused by data that should not have survived the previous build.

## Root cause: `up --build` does not recreate postgres

The postgres service has no volume, so its data lives in the **container's
writable layer**. That is wiped when the *container* is recreated, not when the
image is rebuilt. `docker compose up -d --build` only recreates a container
whose image or config changed. Rebuilding the app image leaves the postgres
container untouched, so its data persists.

Observed directly — after a session of repeated app rebuilds:

```
pg container started:  2026-08-04T19:29:10Z     ← untouched for hours
app container started: 2026-08-04T21:47:49Z     ← recreated many times
```

The comment "starts empty every time" is true per *container lifetime*, not per
build, which is easy to read the other way.

**Confirmed empirically**, not inferred — create a marker space, rebuild, look
for it:

```
$ curl -X POST .../api/spaces -d '{"space":"zz_persist_probe", ...}'   → created
$ docker compose -f docker-compose.test.yml up -d --build --wait       → exit 0
$ docker inspect vitalgraph-test-pg --format '{{.State.StartedAt}}'
  2026-08-04T19:29:10Z          ← unchanged; the container was never recreated
$ curl .../api/spaces | grep zz_persist_probe                          → still present
```

Compounding it, the usage block at `docker-compose.test.yml:15` documents
exactly the path that never resets:

```
#   docker compose -f docker-compose.test.yml up -d --build --wait
```

`e2e/run-tests.sh` gets this right — it runs `down --remove-orphans` on exit
(unless `--no-down`), so the sanctioned path does start clean. The problem is
that the compose file's own documented invocation does not, and that is what
anyone iterating by hand will use.

## The registry tombstones specifically

`DELETE /api/registry/entities/delete` is a **soft delete**: the row stays with
`status='deleted'` and continues to match searches, because the list endpoint's
`status` filter defaults to `active` but is commonly called with `status=''`
(no filter) which returns tombstones too.

This already caused a real failure. `entity-registry-lookups.spec.ts` cleanup
passed `limit: 50` — but the endpoint's parameter is `page_size` (default 20),
so `limit` was ignored. Once 20 tombstones preceded the live row, cleanup's
window contained only tombstones, it deleted nothing, and each run left another
**live** duplicate behind until `getByText(SOURCE_NAME)` matched two rows and
failed strict mode. Fixed in the spec by paging through and skipping deleted
rows (see `issues/022`), so the test is green — **but the tombstones keep
accumulating**: `E2E Lookup Source Sel` alone has 53.

Purging them is a registry-row deletion and there is **no hard-delete API
path** — `entity_registry_impl.delete_entity` soft-deletes; nothing exposes a
purge. Clearing them today means direct SQL.

## Suggested fixes

In rough order of value:

1. **Make the documented start path reset the database.** Change the usage block
   to `down` then `up -d --build --wait`, or add a `--force-recreate postgres`
   note. One line of documentation removes the whole class.
2. **Reword the misleading comment** on the postgres service: "no volumes — data
   lives in the container layer and is wiped only when the container is
   recreated, not on image rebuild."
3. ~~**Make seeding idempotent.**~~ ✅ **DONE (2026-08-04).**
   `_seed_entity_registry` called `create_entity` unconditionally, and
   `primary_name` has no unique constraint, so every seed run added another
   `E2E Registry Person`. It now looks the entity up first via
   `search_entities(status="active")` — which excludes tombstones, so a
   soft-deleted row does not make the seed think the entity still exists — and
   compares `primary_name` exactly, since the query is an ILIKE over names and
   aliases and can return near-matches.

   Verified both branches: against a scratch name, 3 seed runs produce exactly
   1 entity (create, then skip, then skip); against the live stack the seed now
   reports the 2 pre-existing duplicates and creates nothing, where before each
   run added one.

   Pre-existing duplicates are **reported, not deleted** — a seed script
   removing registry rows is a bigger decision than it looks, and each delete
   would add another tombstone, which is the growth this issue is about. The
   warning names the offending IDs:

   ```
   WARNING Entity-registry has 2 live entries named 'E2E Registry Person'
           (expected 1): e_7s0p9getyr, e_v9oxjq89my —
           duplicates can break name-based UI assertions
   ```
4. **Decide the tombstone policy.** Either give the registry a hard-delete /
   purge path for test and admin use, or have the E2E cleanup hard-delete via
   whatever mechanism is chosen. Note the general trap: an endpoint whose
   default `status` filter hides tombstones while `status=''` reveals them makes
   "is it there?" ambiguous for every caller.
5. **Consider whether `status=''` should mean "any non-deleted"** rather than
   "literally everything". Callers asking for "no status filter" almost never
   mean "include the graveyard", and that reading is what made cleanup subtly
   wrong.

## Related

- `issues/022` — several failures traced to this residue; the FileNode leak
  (103 orphans) and its `graph_id`-less delete are documented there and fixed.
- `issues/034` — same family: `DELETE /api/spaces` and the registry delete both
  report success for outcomes that did nothing.
