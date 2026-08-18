# A Failed Bulk Write Is Reported As Success

## Status: OPEN — traced end to end, not yet fixed

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
