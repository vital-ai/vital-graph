# 262 — An older save can overwrite a newer frame, and only the write transaction can stop it

## Status: REFUSED 2026-10-06 — an incorrect request, not a database defect.
## It asks VitalGraph to reorder writes by a caller-supplied sequence
## (`write_seq` / `hasFrameWriteSeq`). A database applies writes in the order
## they arrive; keeping writes to one entity in order is the caller's job.
## Nothing built; nothing to build here.

## What was requested

Raised by a caller. Its saves for one entity reach VitalGraph out of order, and
since frame `upsert` replaces the frame graph (`256`), whichever save arrives
last is what remains — so an older save that arrives late replaces a newer one.

The request: store a server-managed sequence ON each frame
(`haley-ai-kg#hasFrameWriteSeq`); accept an optional `write_seq` on every frame
write; inside the write transaction drop each named frame whose stored sequence
is newer, set the sequence on what is written, and answer `superseded_frames`
(all stale → `status: "superseded"`).

## Why it is refused

### 1. Last write to arrive wins — that is what a database does

VitalGraph, like any database, applies writes in the order it receives them and
commits them in that order. It cannot know which of two writes the caller
INTENDED as newer, and it should not guess from a number the caller attaches.
Nothing here is lost or corrupted by VitalGraph: each write does exactly what it
says, when it arrives.

A caller that needs its writes applied in order does what every database caller
does:

- **wait for a write's outcome before sending the next write to the same data;**
- **after a timeout, settle the outcome first** — retry the same write (it is
  idempotent) or read back — before sending anything newer;
- or **use optimistic concurrency**: send `if_unmodified_since` with the stamp
  the data was based on, so a write built on stale data is refused with
  `conflict` instead of applied.

The described out-of-order arrivals come from a writer that does none of these:
it mirrors each upstream change as an independent background task, writes the
snapshot carried by that change rather than current state, retries a failed task
later with the same snapshot, and re-reads the CURRENT stamp before each attempt
(and again on `conflict`) — so the guard never carries the stamp its data was
based on. Fixing that is the caller's change: mirror current state, or serialise
and coalesce per entity, and send the stamp the data was based on.

### 2. A caller-supplied ordering clock is not a database facility

`write_seq` is the caller's own scheme (added on its side on 2026-09-30; it has
never existed in VitalGraph), and its value is a wall-clock time taken by the
caller. Storing it on every frame and silently dropping writes it ranks lower
would make the store resolve one caller's ordering problem for every caller —
and turn what should be a visible `conflict` into a write that quietly did not
happen.

### 3. The tools VitalGraph already gives are the database-correct ones

- The entity lock serialises writes to one entity, server-side.
- `if_unmodified_since` refuses a stale write with `conflict`.
- Frame `create` refuses an existing frame, `update` is all or nothing, and
  `upsert` replaces exactly the frames named (`256`, 0.0.46).

### For the record

Had it been built it would also have needed: a new ontology property (a domain
release); carrying the value forward through writes that do not send it; a
64-bit type (epoch milliseconds overflow `xsd:int`); tombstones for deletes; a
`replace` rule for a stale frame's descendants; and a new `superseded` status
and response field in the models and the client. `hasFrameSequence` is not a
substitute: it is the caller-set position of a frame among its siblings and the
frame sort key.
