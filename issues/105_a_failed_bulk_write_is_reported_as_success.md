# A Failed Bulk Write Is Reported As Success

## Status: FIXED 2026-08-18 — the write raises; five methods had this, not one

`return 0` became `raise`, keeping the log line. The callers were already written
for it, which is why this was the right shape and not the result-object
alternative below.

**Five methods, not the one this issue named.** `add_rdf_quads_batch`,
`add_rdf_quads_batch_bulk`, `delete_entity_graph_bulk`,
`remove_rdf_quads_batch_bulk`, `remove_rdf_quads_batch` all had the identical
swallow. Fixing only the named one would have left DELETES silently failing, and
`update_quads` calls both a remove and an add.

**Nothing above needed changing.** `update_quads` already had
`try -> return True / except -> return False`; the `except` was simply
unreachable. It now returns False.

**The stalled-queue worry was unfounded**, and that was checked rather than
assumed: `segmentation_worker._process_job` catches `Exception`, increments
`_jobs_failed` and calls `manager.fail(job_id, reason)`. A raised exception
becomes a failed job with a recorded cause, not a stuck queue.

**Blast radius, by AST rather than by grep:** 8 of 34 call sites are not inside a
`try`. Six are thin delegating wrappers or the fuseki backend. The other two —
`kgdocuments_endpoint._store_segmentation_output` and
`kgrelations_endpoint._store_relations_in_space` — are DEAD: their enclosing
chains (`_handle_segment_sync`, `_execute_segmentation`) have no callers. Every
live call site was already wrapped.

**A second lie, one layer out.** Three callers logged `"Stored {len(quads)}
quads"` with the count they handed IN, immediately after the call — so a failed
or partial write printed a success line. They now log what the write returned.

**Verified against the real failure**, by renaming `sp_kg_types_entity_slot_sort`
away — the actual `issues/100` condition, not a mock:

    before   returned 0        update_quads -> True
    after    raises            update_quads -> False
             UndefinedTableError naming the missing table

`tests/integration/test_failed_write_is_not_success.py`. Both failure tests fail
on the pre-fix code; a third asserts the healthy path still returns a count and
that an empty write is still a legitimate zero — without it, "always raise" would
also pass.

### `get_rdf_quad_count` should NOT be changed — reviewed 2026-08-18

It has the same swallow, and leaving it was recorded here as unfinished work.
Having reviewed the call sites, changing it would be a no-op at best and a
regression at worst.

**Both product call sites already treat a failure as zero, by their own choice.**
`list_graphs` (:280) and `get_graph` (:303) each wrap the call in
`try/except Exception: pass` around `triple_count = 0`. If the count raised, they
would still display 0 — the same output — except the exception would be
discarded by a bare `except: pass` with NO log, where today the impl logs the
cause. Raising would delete the only record of what went wrong.

**The count is a display field, not a decision input.** It reaches
`sparql_graph_endpoint` as `triple_count` on the graph listing. A wrong 0 is an
inaccurate number on a page, not a wrong plan or a lost write. Contrast the bulk
write, where the same shape cost `issues/100` two days and six broken searches.

**The persistent form of the risk is already guarded.**
`tests/unit/test_count_caching.py` asserts a failed count is NOT cached, with the
reason in the test: "a failed count was cached as 0 — an outage now looks like an
empty graph for the life of the entry". Someone reached this conclusion already
and handled the part that actually bites.

If the display accuracy ever matters, the fix is at the call sites — report
"unknown" rather than 0 — not at the impl. That is an API contract change and is
not proposed here.

## The original report

`add_rdf_quads_batch_bulk` catches every exception, logs it, and returns 0:

    except Exception as e:
        logger.error("add_rdf_quads_batch_bulk(%s) failed: %s", space_id, e)
        return 0

A failed write and a write of nothing then look identical to every caller, and
only one of nine tells them apart.

## The trace, from `issues/100`

That issue's six failing searches were this defect, three layers deep:

1. `add_rdf_quads_batch_bulk` fails — `relation "sp_kg_types_entity_slot_sort"
   does not exist` — logs at ERROR, returns 0.
2. `kg_backend_utils.update_quads` **discards the return** and `return True`.
   It has a `try/except Exception -> return False`, which the swallow one layer
   down makes unreachable: nothing raises, so nothing is caught.
3. `kgtypes_create_impl.create_kgtype` DOES check —
   `if not success: raise Exception("Failed to create KGType - update_quads
   returned False")` — and receives True.
4. The API reports the types created. Nothing was written. Every subsequent
   search returns zero, for a reason no layer reported.

Three separate error checks, each written by someone who expected to catch this,
all defeated by a `return 0` at the bottom.

## Who checks

Nine call sites, one check:

    kg_backend_utils.store_objects:830        CHECKS — `if inserted == 0 and
                                              len(quads) > 0` -> success=False
    kg_backend_utils.update_quads:1195        discards, returns True
    kg_backend_utils.update_entity_graph:1257 discards
    kg_backend_utils.update_entity_subject_only:1307  discards
    kg_backend_utils.update_subjects_graph:1361       discards
    document/segmentation_worker.py:709       discards
    document/auto_segmentation.py:241         discards
    endpoint/kgdocuments_endpoint.py:794      discards

`store_objects`'s check is also a heuristic rather than a signal — it infers
failure from "0 inserted with a non-empty input", which is why its message says
"likely a PostgreSQL index overflow or constraint error". It cannot say what
happened because the exception was discarded before it.

## Why the swallow is the wrong shape here

The comment on it is not preserved anywhere, so the intent is inferred: keeping a
bulk write from taking down a caller. But the effect is that a write failure is
indistinguishable from a no-op, and every layer above has to guess.

Two directions, neither obviously right without knowing why it was added:

* **Raise.** The three callers above already have `except Exception` blocks
  waiting for it, and `update_quads` would then correctly `return False`. This is
  the smallest change and makes the existing error handling work as written.
* **Return a result rather than a count** — inserted count plus an error — so a
  caller can tell 0-because-empty from 0-because-failed without inferring.

Raising is likely right precisely because the callers were already written for
it, but the callers that DISCARD the return would then start propagating
exceptions they currently never see, and those paths need looking at first —
particularly the segmentation worker, which runs in the background and whose
failure mode is a stalled queue rather than a failed request.

## How this stayed invisible

The error was logged, at ERROR, with the exact cause. Four times. Nobody saw it
because the request succeeded — and a green request is not a reason to read the
server log.

`issues/100` took two days and three wrong hypotheses to reach that log line.

## Related

- `issues/100` — the six searches this produced, and the two days of wrong
  hypotheses it cost
- `issues/103` — the same shape one layer out: a stats resync that failed and
  left a space silently degraded, fixed by making the failure impossible to
  leave behind rather than by reporting it better
