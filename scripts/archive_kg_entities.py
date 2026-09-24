#!/usr/bin/env python3
"""Copy KG entity graphs from one space to another, through the VitalGraph API.

Built to archive nurture actions out of `prod_kg` into `prod_kg_archive`
by calendar month, but the type URI and both spaces are arguments.

THIS SCRIPT NEVER DELETES ANYTHING. Deleting the originals is a separate step,
to be run only after `verify` passes against the copy.

Three phases, each resumable:

    plan    enumerate the entity URIs for the requested months into a queue file
    copy    drain the queue -- read each entity GRAPH, insert its quads in the
            target space -- appending to a done file as it goes
    verify  re-count both spaces per month and diff a sample of entity graphs
            quad-for-quad

    python scripts/archive_kg_entities.py plan   --env prod --months 2026-05,2026-06,2026-07
    python scripts/archive_kg_entities.py copy   --env prod
    python scripts/archive_kg_entities.py verify --env prod

THE WRITE PATH. `POST /api/graphs/kgentities` with
`preserve_object_properties=true`. The flag matters: without it that path
stamps `objectCreationTime = now` on every entity, which would date the whole
archive to the day of the copy -- the field the archive is organised by, with
the originals due for deletion afterwards.

Going through the KG entity path rather than raw quads means the copy gets the
same server-side bookkeeping a normal write gets: entity-structure validation,
grouping URIs, cache invalidation and auto-sync, on top of the derived tables
(`edge`, `frame_slot`, `entity_slot_sort`, `entity_prop_sort`,
`frame_prop_sort`) that any insert maintains.

WHY RE-RUNNING IS SAFE. An entity already in the target comes back
`already_exists` -- a domain outcome, HTTP 200, nothing written and nothing
overwritten. So a run interrupted midway is repaired by running `copy` again.
The done file saves re-reading; it is not what makes this safe.

WHAT THE COPY CHANGES ON PURPOSE. The create path stamps
`hasKGFormType = Aspect` on entity-enclosed frames that arrive without one.
Production omits the marker and relies on the unset default, which reads as
Assertion, so nearly every copied entity gains these quads. Confirmed
2026-09-24 that entity-enclosed frames SHOULD be Aspects: this is the copy
normalising data the source never marked. `verify` reports it as normalisation
and passes; any OTHER quad the target has and the source does not still fails.
See `NORMALISED_ADDITIONS`.

INDEXING IS HANDLED PER INSERT, which is a reason to use this endpoint rather
than raw quads. `_create_or_update_entities` calls `_schedule_auto_sync`, and
`auto_sync._run_sync` covers all four: vectors, geo, fuzzy and FTS. Measured in
dev -- the target's `message_content` index went from 0 rows to 1,329 purely as
a result of copying, with no populate call.

VERIFIED COMPLETE, not just non-empty. Attributing FTS rows to the 688 copied
entities by exact-or-child URI match: 1,327 rows in the source, 1,327 in the
target, ZERO subjects present in one and not the other. The target's 2 extra
rows belong to an entity copied by an earlier test, not to this run.

An earlier pass through this data reported a ~4% shortfall and blamed auto-sync
for losing work under 20-way concurrency. THAT WAS WRONG, and the way it was
wrong is worth keeping: rows were attributed to entities with
`split_part(subject_uri, ':frame:', 1)`, which for subjects that contain no
`:frame:` returns the whole URI, so the comparison silently pulled in seeded and
TEST entities that were never copied at all. The three "worst offenders" turned
out to be absent from the queue. A heuristic that maps a row to the wrong entity
does not fail loudly -- it produces a plausible percentage.

It IS fire and forget -- "failures are logged but never block the response", and
the work runs in a background task after the write returns -- so `verify` still
reports the index row counts rather than assuming them. Nothing measured here
says it drops work; if a target index ever does come up short, the backfill is:

    POST /api/fts-indexes/populate?space_id=<dst>&index_name=message_content
      body: {"graph_uri": "<graph>"}   (422 without it)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Defaults are PLACEHOLDERS, not a deployment's real identifiers — this
# repository does not carry those. Override per run with the flags, or set
# the VG_ARCHIVE_* environment variables once and omit them.
DEFAULT_TYPE = os.environ.get("VG_ARCHIVE_TYPE", "urn:example:kg:entity:NurtureAction")
DEFAULT_SRC = os.environ.get("VG_ARCHIVE_SRC", "prod_kg")
DEFAULT_DST = os.environ.get("VG_ARCHIVE_DST", "prod_kg_archive")
DEFAULT_GRAPH = os.environ.get("VG_ARCHIVE_GRAPH", "urn:prod_kg")
CREATED_URI = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
ENTITY_TYPE_PRED = "<http://vital.ai/ontology/haley-ai-kg#hasKGEntityType>"

# Quads the WRITE PATH legitimately adds that the source does not have, keyed by
# (predicate, object) so a different value for the same predicate still fails.
#
# `hasKGFormType = Aspect`: the KG entity create path stamps this on every
# entity-enclosed frame that arrives without one
# (`kg_impl/kgentity_create_impl.py`, "Step 4b"). Production omits the marker --
# 318 frames across 25 sampled nurture actions carried 5 of them -- and relies
# on the unset default, which reads as Assertion. Confirmed 2026-09-24 that
# entity-enclosed frames SHOULD be Aspects, so the copy is normalising data the
# source never marked, not corrupting it.
#
# Anything NOT listed here that appears in the target and not the source fails
# `verify`. The point of the table is that each addition is a decision somebody
# made, recorded with its reason, rather than a diff quietly tolerated.
NORMALISED_ADDITIONS = {
    ("<http://vital.ai/ontology/haley-ai-kg#hasKGFormType>",
     "<http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect>"),
}


# --------------------------------------------------------------------------
# env / transport
# --------------------------------------------------------------------------

def load_env() -> dict:
    values = {}
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        values[k.strip()] = v
    return values


class Api:
    """Thread-safe API client that renews its own token.

    THE TOKEN OUTLIVES NOTHING. `/api/login` issues ~1,799s (~30 min) of
    validity and the full archive copy is ~65 minutes, so a client that logs in
    once WILL start getting 401s partway through a real run -- a 1,387-entity
    delete already lost 10 entities that way. Re-login once on a 401 and retry;
    the alternative is every long job having to be restarted and resumed around
    an entirely predictable clock.
    """

    def __init__(self, base, user, password, retries=4, timeout=600):
        self.base = base.rstrip("/")
        self.retries = retries
        self.timeout = timeout
        self._creds = (user, password)
        self._auth_lock = threading.Lock()
        self.token = self._login(user, password)
        self.logins = 1

    def _relogin(self, stale):
        """Renew the token unless another thread already did.

        Compare-and-set on the token we were using: twenty workers hitting a
        401 at the same moment must produce ONE login, not twenty.
        """
        with self._auth_lock:
            if self.token != stale:
                return self.token
            self.token = self._login(*self._creds)
            self.logins += 1
            return self.token

    def _raw(self, method, path, data, headers):
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def _login(self, user, password):
        body = urllib.parse.urlencode({"username": user, "password": password}).encode()
        return self._raw("POST", "/api/login", body,
                         {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]

    def _call(self, method, path, body=None):
        stale = self.token
        headers = {"Authorization": f"Bearer {stale}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        last = None
        for attempt in range(self.retries):
            try:
                return self._raw(method, path, data, headers)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt < self.retries - 1:
                    # Expired, not forbidden: renew and retry immediately.
                    headers["Authorization"] = f"Bearer {self._relogin(stale)}"
                    continue
                # 5xx is a genuine server fault here (domain outcomes come back
                # as HTTP 200) and the one seen in practice -- a statement
                # cancelled by the 60s timeout -- succeeds on retry.
                if e.code < 500 or attempt == self.retries - 1:
                    detail = ""
                    try:
                        detail = e.read().decode()[:300]
                    except Exception:
                        pass
                    raise RuntimeError(f"HTTP {e.code} on {method} {path}: {detail}") from None
                last = e
                time.sleep(2 ** attempt)
            except urllib.error.URLError as e:
                if attempt == self.retries - 1:
                    raise
                last = e
                time.sleep(2 ** attempt)
        raise last

    def get(self, path, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self._call("GET", f"{path}?{q}")

    def post(self, path, body, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self._call("POST", f"{path}?{q}", body)


def connect(env_name: str, env: dict) -> Api:
    if env_name == "dev":
        return Api(env["LOCAL_CLIENT_SERVER_URL"], env["LOCAL_CLIENT_AUTH_USERNAME"],
                   env["LOCAL_CLIENT_AUTH_PASSWORD"])
    return Api(env["PROD_CLIENT_SERVER_URL"], env["PROD_AUTH_ROOT_USERNAME"],
               env["PROD_AUTH_ROOT_PASSWORD"])


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

class State:
    """A queue, a done log and a failure log, all append-only files."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue = root / "queue.jsonl"
        self.done = root / "done.jsonl"
        self.failed = root / "failed.jsonl"

    def write_queue(self, rows):
        tmp = self.queue.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        tmp.replace(self.queue)

    def read_queue(self):
        if not self.queue.exists():
            return []
        return [json.loads(l) for l in self.queue.read_text().splitlines() if l.strip()]

    def done_uris(self) -> set:
        if not self.done.exists():
            return set()
        out = set()
        for l in self.done.read_text().splitlines():
            if l.strip():
                try:
                    out.add(json.loads(l)["uri"])
                except Exception:
                    continue
        return out

    def append(self, path: Path, row: dict):
        with open(path, "a") as fh:
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def month_bounds(month: str):
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return start, end


def count(api, space, graph, type_uri, after=None, before=None) -> int:
    d = api.get("/api/graphs/kgentities/count", space_id=space, graph_id=graph,
                entity_type_uri=type_uri, created_after=after, created_before=before)
    n = d.get("count")
    return d.get("total_count", 0) if n is None else n


def entity_uris_in_window(api, space, graph, type_uri, after, before, page_size):
    """Entity URIs created in [after, before), by offset paging inside the window.

    Windowed by DAY at the call site so the offset stays small: offset paging
    over a sorted index is O(offset), and a month of 31,000 rows read in pages
    of 200 would spend most of its time re-walking the prefix.
    """
    seen, offset = [], 0
    while True:
        d = api.get("/api/graphs/kgentities", space_id=space, graph_id=graph,
                    entity_type_uri=type_uri, created_after=after,
                    created_before=before, sort_by=CREATED_URI, sort_order="asc",
                    page_size=page_size, offset=offset)
        rows = d.get("results") or []
        if not rows:
            return seen, d.get("total_count", 0)
        found = [r["s"] for r in rows if r.get("p") == ENTITY_TYPE_PRED]
        if not found:
            # No entity-typing quad in this page: the page holds only
            # continuation rows, so stop rather than loop forever.
            return seen, d.get("total_count", 0)
        seen.extend(found)
        offset += page_size
        if offset >= d.get("total_count", 0):
            return seen, d.get("total_count", 0)


def fetch_entity_graph(api, space, graph, uris, allow_missing=False):
    """Entity graphs for `uris`, refusing a short answer.

    The server now reports a shortfall rather than quietly returning less
    (`issues/229`): `incomplete` is True when a read FAILED and is retryable,
    and `missing_uris` lists everything asked for and not returned. A read that
    silently came back short is what removed 113 of 500 entities from a copy
    that reported success, so a short answer is raised here rather than
    forwarded to the writer.

    `incomplete is None` means the server predates the fix and cannot say; fall
    back to counting entity subjects, which is the check that caught it before
    the server could report it.

    `allow_missing` is for the callers where ABSENCE IS THE FINDING rather than
    a fault -- reading the target to see what did or did not arrive, or to
    confirm a delete. Those callers compare the two sides themselves; raising
    would turn their answer into an exception.
    """
    d = api.get("/api/graphs/kgentities", space_id=space, graph_id=graph,
                uri_list=",".join(u.strip("<>") for u in uris),
                include_entity_graph="true", page_size=len(uris))
    rows = d.get("results") or []
    missing = d.get("missing_uris") or []
    if missing and not allow_missing:
        raise RuntimeError(
            f"read returned {len(uris) - len(missing)} of {len(uris)} entity "
            f"graphs (incomplete={d.get('incomplete')}); first missing: "
            f"{missing[0]}")
    if d.get("incomplete") is None and not allow_missing:
        got = len({r["s"] for r in rows if r.get("p") == ENTITY_TYPE_PRED})
        if got != len(uris):
            raise RuntimeError(
                f"read returned {got} of {len(uris)} entity graphs and the "
                f"server did not report a shortfall — counted locally")
    return rows


def insert_entity_graph(api, space, graph, quads):
    """Insert one entity graph through the KG entity create path.

    Returns (quads_written, already_present).

    `preserve_object_properties=true` is what makes this usable for an archive:
    without it the path stamps `objectCreationTime = now` on every entity, and
    the archive is organised by creation month.

    The graph goes in ONE request rather than being chunked by quad count --
    the processor validates entity structure, so a chunk that separated an
    entity from its frames would be rejected.

    `already_exists` is a domain outcome, not a failure: it is what a resumed
    run sees for everything it copied before the interruption. The caller
    confirms the target actually holds the graph rather than trusting the
    status.
    """
    body = {"quads": [{"s": q["s"], "p": q["p"], "o": q["o"]} for q in quads]}
    expected = len({q["s"] for q in quads if q["p"] == ENTITY_TYPE_PRED})
    r = api.post("/api/graphs/kgentities", body, space_id=space, graph_id=graph,
                 operation_mode="create", preserve_object_properties="true")
    status = str(r.get("status", "")).lower()
    if status == "already_exists":
        return 0, True
    if status not in ("created", "ok", "success"):
        raise RuntimeError(f"kgentities insert status={r.get('status')}: {r.get('message')}")

    # COUNT WHAT CAME BACK. A `created` status is not a promise that everything
    # sent was written: at `--batch 100 --parallel 10` against production, 113
    # of 500 entities never landed while every request reported success and the
    # queue recorded all 500 as done. Trusting the status is how a copy loses
    # 23% of its rows and still says PASS.
    created = r.get("created_count")
    if created is None:
        created = len(r.get("created_uris") or [])
    if expected and created != expected:
        raise RuntimeError(
            f"insert reported {status} but created {created} of {expected} "
            f"entities sent — treating as a failure so the batch is retried")
    return len(quads), False


def copy_batch(api, a, uris):
    """Copy a batch of entity graphs. Returns (quads_written, already_present).

    The batch is fetched in one request and posted in one request, which is
    where the throughput comes from. `already_exists` applies to the WHOLE
    post, though, so a batch holding even one entity that is already in the
    target would otherwise strand the rest -- and that is exactly the shape of
    a resumed run whose done log is missing or stale. On that status only, fall
    back to one entity at a time so the rest still land.
    """
    quads = fetch_entity_graph(api, a.src, a.src_graph, uris)
    if not quads:
        raise RuntimeError("entity graph came back empty")
    written, already = insert_entity_graph(api, a.dst, a.dst_graph, quads)
    if not already:
        # Read it back. Costs one extra fetch per batch and is the difference
        # between a copy that is complete and one that merely says it is.
        confirm_present(api, a.dst, a.dst_graph, uris, quads)
        return written, 0
    if len(uris) == 1:
        # The unit IS one entity, so there is nothing to split and the graph is
        # already in hand -- re-fetching and re-posting it would double the
        # work of every already-present entity on a resumed run.
        confirm_present(api, a.dst, a.dst_graph, uris, quads)
        return 0, 1

    written, already_n = 0, 0
    for uri in uris:
        one = fetch_entity_graph(api, a.src, a.src_graph, [uri])
        if not one:
            raise RuntimeError(f"entity graph came back empty for {uri}")
        n, was_there = insert_entity_graph(api, a.dst, a.dst_graph, one)
        written += n
        if was_there:
            already_n += 1
            # Trust nothing: the status says it is there, so prove it is.
            confirm_present(api, a.dst, a.dst_graph, [uri], one)
    return written, already_n


_TIMESTAMP_PREDS = (
    "<http://vital.ai/ontology/vital-aimp#hasObjectCreationTime>",
    "<http://vital.ai/ontology/vital#hasObjectModificationDateTime>",
)


def confirm_present(api, space, graph, uris, expected):
    """Every quad in `expected` must be readable back from the target.

    THE ONLY TRUSTWORTHY CHECK. The response status lies -- `created` came back
    for batches that wrote nothing -- and so does `created_count`: adding a
    count check still left 13 of 900 entities recorded as done and absent from
    the target. Reading the target back is the one thing that cannot be wrong
    about what is in the target.
    """
    got = {(q["s"], q["p"], q["o"])
           for q in fetch_entity_graph(api, space, graph, uris, allow_missing=True)}
    missing = {(q["s"], q["p"], q["o"]) for q in expected} - got
    if _ALLOW_RESTAMP[0]:
        # The server restamped them on purpose; a difference here is expected
        # and would otherwise drown out real loss.
        missing = {t for t in missing if t[1] not in _TIMESTAMP_PREDS}
    if missing:
        raise RuntimeError(
            f"target is missing {len(missing)} of {len(expected)} quads after insert; "
            f"first: {list(missing)[0][1]}")


# --------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------

def phase_plan(api, a, st: State):
    months = [m.strip() for m in a.months.split(",") if m.strip()]
    print(f"planning: {a.type_uri}\n  {a.src} -> {a.dst}  months={months}")
    rows, expected_total = [], 0
    for month in months:
        start, end = month_bounds(month)
        expected = count(api, a.src, a.src_graph, a.type_uri,
                         f"{start}T00:00:00", f"{end}T00:00:00")
        expected_total += expected
        got = []
        day = start
        while day < end:
            nxt = day + timedelta(days=1)
            uris, _ = entity_uris_in_window(api, a.src, a.src_graph, a.type_uri,
                                            f"{day}T00:00:00", f"{nxt}T00:00:00",
                                            a.page_size)
            got.extend(uris)
            day = nxt
        uniq = list(dict.fromkeys(got))
        print(f"  {month}: api count={expected:,}  enumerated={len(got):,}  "
              f"distinct={len(uniq):,}" +
              ("" if len(uniq) == expected else "   <-- MISMATCH"))
        rows.extend({"uri": u, "month": month} for u in uniq)

    allu = list(dict.fromkeys(r["uri"] for r in rows))
    print(f"\n  total distinct entities queued: {len(allu):,} "
          f"(api total for these months: {expected_total:,})")
    if len(allu) != expected_total:
        print("  WARNING: enumeration does not match the counts. The queue is a "
              "SUBSET or has overlap; fix before copying.")

    # Size the copy from a real sample rather than guessing -- and sample at
    # RANDOM across the queue, not off the front. Entity graphs here range from
    # ~250 to ~1,000 quads and the queue is in creation order, so the first
    # twenty are not representative: head-sampling estimated 11M quads where a
    # spread sample of 90 says 24M.
    if allu:
        import random
        rnd = random.Random(a.sample_seed)
        picks = rnd.sample(allu, min(a.plan_sample, len(allu)))
        sizes = []
        for i in range(0, len(picks), 5):
            part = picks[i:i + 5]
            sizes.append(len(fetch_entity_graph(api, a.src, a.src_graph, part)) / len(part))
        per = sum(sizes) / len(sizes)
        print(f"  sampled {len(picks)} entity graphs at random: {per:,.0f} quads "
              f"each on average (batch means {min(sizes):,.0f}..{max(sizes):,.0f})"
              f"\n  -> ~{per * len(allu):,.0f} quads to copy")

    st.write_queue(rows)
    print(f"\nqueue written: {st.queue}  ({len(rows):,} rows)")
    print("next: copy")


_ALLOW_RESTAMP = [False]


def assert_server_supports_preserve(api) -> None:
    """Refuse to copy against a server that cannot preserve timestamps.

    FastAPI IGNORES an unknown query parameter rather than rejecting it, so
    `preserve_object_properties=true` against a server built before the flag
    existed is silently a no-op -- the copy succeeds, reports success, and
    stamps every entity with the time of the copy. That is not a hypothetical:
    it put 1,000 nurture actions into the production archive dated 2026-09-24
    instead of May, because the code was on the dev image and had never been
    deployed. Nothing in the response distinguished it from a correct run; only
    `verify` caught it, afterwards.

    So ask the server what it accepts, before writing anything.
    """
    try:
        spec = api._call("GET", "/openapi.json")
        params = [p["name"] for p in
                  spec["paths"]["/api/graphs/kgentities"]["post"].get("parameters", [])]
    except Exception as e:
        raise SystemExit(
            f"cannot read the server's OpenAPI spec to check for "
            f"preserve_object_properties: {e}")
    if "preserve_object_properties" not in params:
        if _ALLOW_RESTAMP[0]:
            print("!! --allow-restamp: this server CANNOT preserve timestamps.\n"
                  "!! Every entity copied by this run will be dated NOW, not its\n"
                  "!! real creation date. Throughput measurement only — delete\n"
                  "!! what it writes with scripts/delete_kg_entities.py.\n", flush=True)
            return
        raise SystemExit(
            "REFUSING TO COPY: this server's POST /api/graphs/kgentities does not\n"
            "accept `preserve_object_properties`, so it would stamp every copied\n"
            "entity with the current time instead of keeping its real creation\n"
            f"date. Accepted parameters: {params}\n"
            "Deploy a build containing the flag, then re-run.")


def phase_copy(api, a, st: State):
    rows = st.read_queue()
    if not rows:
        print("queue is empty — run `plan` first")
        return 1
    done = st.done_uris()
    todo = [r for r in rows if r["uri"] not in done]
    print(f"copy: {len(rows):,} queued, {len(done):,} already done, "
          f"{len(todo):,} to go  ({a.src} -> {a.dst}, graph {a.dst_graph})")
    if a.limit:
        todo = todo[:a.limit]
        print(f"  --limit {a.limit}: this run will process {len(todo):,}")
    print(f"  {a.parallel} workers, {a.batch} entit"
          f"{'y' if a.batch == 1 else 'ies'} per request")
    if a.dry_run:
        print("  DRY RUN — nothing will be written")
        return 0
    assert_server_supports_preserve(api)

    units = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    started = time.time()
    tally = {"quads": 0, "already": 0, "failed": 0, "entities": 0}
    # One lock for the counters AND the append-only logs. The logs are the
    # resume record: a torn line there would be read back as a missing or
    # malformed entry on the next run, so they are not worth the contention
    # saved by a second lock.
    lock = threading.Lock()
    stop = threading.Event()

    def work(unit):
        if stop.is_set():
            return
        uris = [r["uri"] for r in unit]
        try:
            n, already_n = copy_batch(api, a, uris)
            with lock:
                tally["quads"] += n
                tally["already"] += already_n
                tally["entities"] += len(unit)
                for r in unit:
                    st.append(st.done, {"uri": r["uri"], "month": r["month"],
                                        "ts": datetime.now().isoformat(timespec="seconds")})
        except Exception as e:
            with lock:
                tally["failed"] += len(unit)
                tally["entities"] += len(unit)
                for r in unit:
                    st.append(st.failed, {"uri": r["uri"], "month": r["month"],
                                          "error": str(e)[:300]})
                print(f"  FAILED {uris[0][:70]}: {str(e)[:160]}", flush=True)
            if a.stop_on_error:
                stop.set()
        if a.sleep:
            time.sleep(a.sleep)

    done_units = 0
    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        futures = {pool.submit(work, u): u for u in units}
        for fut in as_completed(futures):
            fut.result()
            done_units += 1
            if done_units % a.report_every == 0 or done_units == len(units):
                with lock:
                    n_ent = tally["entities"]
                    el = time.time() - started
                    rate = n_ent / el if el else 0
                    eta = (len(todo) - n_ent) / rate if rate else 0
                    print(f"  {n_ent:,}/{len(todo):,} entities, {tally['quads']:,} quads, "
                          f"{rate:.1f} ent/s, eta {eta/60:.0f}m, "
                          f"{tally['already']} already, {tally['failed']} failed", flush=True)

    el = time.time() - started
    print(f"\ndone in {el/60:.1f}m: {tally['quads']:,} new quads, "
          f"{tally['already']:,} entities already present, {tally['failed']} failures "
          f"({tally['entities']/el if el else 0:.1f} ent/s)")
    if stop.is_set():
        print("  stopped early on --stop-on-error; re-run `copy` to continue")
    if tally["failed"]:
        print(f"  failures logged to {st.failed} — re-run `copy` to retry them")
    print("next: verify")
    return 1 if tally["failed"] else 0


def phase_verify(api, a, st: State):
    rows = st.read_queue()
    months = sorted({r["month"] for r in rows}) or \
        [m.strip() for m in (a.months or "").split(",") if m.strip()]
    queued = Counter(r["month"] for r in rows)
    done = st.done_uris()
    done_by_month = Counter(r["month"] for r in rows if r["uri"] in done)

    print(f"verify: {a.src} -> {a.dst}\n")
    print(f"{'month':<9} {'src':>9} {'dst':>9} {'queued':>9} {'copied':>9}  verdict")
    print("-" * 62)
    ok = True
    for m in months:
        start, end = month_bounds(m)
        s = count(api, a.src, a.src_graph, a.type_uri, f"{start}T00:00:00", f"{end}T00:00:00")
        d = count(api, a.dst, a.dst_graph, a.type_uri, f"{start}T00:00:00", f"{end}T00:00:00")
        good = (d == s)
        ok &= good
        print(f"{m:<9} {s:>9,} {d:>9,} {queued[m]:>9,} {done_by_month[m]:>9,}  "
              f"{'OK' if good else 'SHORT'}")
    print("-" * 62)

    # Counts agreeing is necessary, not sufficient -- it says nothing about
    # whether each entity's GRAPH arrived. Diff a sample quad-for-quad.
    sample = [r["uri"] for r in rows if r["uri"] in done][:a.sample]
    if sample:
        # ONE ENTITY PER DIFF. Batching five into a call and reporting one line
        # per batch undercounted a systematic difference as two entities when
        # it affected all nine -- the count that matters is how many entities
        # differ, so compare them one at a time.
        print(f"\nquad-level diff on {len(sample)} copied entity graphs:")
        missing_n = extra_n = norm_n = 0
        missing_preds, extra_preds, norm_preds = Counter(), Counter(), Counter()
        for uri in sample:
            src = {(q["s"], q["p"], q["o"]) for q in fetch_entity_graph(api, a.src, a.src_graph, [uri])}
            dst = {(q["s"], q["p"], q["o"]) for q in
                   fetch_entity_graph(api, a.dst, a.dst_graph, [uri], allow_missing=True)}
            missing = src - dst
            normalised = {t for t in dst - src if (t[1], t[2]) in NORMALISED_ADDITIONS}
            extra = (dst - src) - normalised
            if missing:
                missing_n += 1
                missing_preds.update(p for _, p, _ in missing)
            if normalised:
                norm_n += 1
                norm_preds.update(p for _, p, _ in normalised)
            if extra:
                extra_n += 1
                extra_preds.update(p for _, p, _ in extra)
        if missing_n:
            ok = False
            print(f"  {missing_n}/{len(sample)} entities are MISSING quads in the target:")
            for p, c in missing_preds.most_common(5):
                print(f"      {c:>5}x {p}")
        if norm_n:
            # Expected, and not a failure: see NORMALISED_ADDITIONS.
            print(f"  {norm_n}/{len(sample)} entities gained NORMALISING quads "
                  f"(expected, see NORMALISED_ADDITIONS):")
            for p, c in norm_preds.most_common(5):
                print(f"      {c:>5}x {p}")
        if extra_n:
            # An addition nobody declared. Fail: the write path is changing the
            # data in a way this script does not know the reason for.
            ok = False
            print(f"  {extra_n}/{len(sample)} entities have UNDECLARED extra quads "
                  f"— the write path is adding something unaccounted for:")
            for p, c in extra_preds.most_common(5):
                print(f"      {c:>5}x {p}")
        if not missing_n and not extra_n and not norm_n:
            print(f"  all {len(sample)} identical")

    # The creation timestamps are the reason for the raw-quad path; check them.
    if sample:
        src_t = _creation_times(api, a.src, a.src_graph, sample[:10])
        dst_t = _creation_times(api, a.dst, a.dst_graph, sample[:10])
        same = sum(1 for u in src_t if src_t.get(u) == dst_t.get(u))
        print(f"\ncreation times preserved: {same}/{len(src_t)}")
        if same != len(src_t):
            ok = False
            for u in list(src_t)[:3]:
                if src_t.get(u) != dst_t.get(u):
                    print(f"  {u[:70]}\n    src={src_t.get(u)}  dst={dst_t.get(u)}")

    # Auto-sync populates these in a background task after the write returns,
    # so they are reported, not assumed. An index that is empty while entities
    # landed means auto-sync did not keep up and needs a populate.
    try:
        idx = api.get("/api/fts-indexes", space_id=a.dst).get("indexes", [])
        if idx:
            print("\nFTS index rows in the target (auto-sync is fire-and-forget):")
            for i in idx:
                st_ = api.get("/api/fts-indexes/stats", space_id=a.dst,
                              index_name=i["index_name"])
                rows_n = st_.get("row_count")
                src_st = api.get("/api/fts-indexes/stats", space_id=a.src,
                                 index_name=i["index_name"])
                src_rows = src_st.get("row_count") or 0
                note = ""
                # REPORTED, NEVER FAILED ON. An index the copied type does not
                # feed is legitimately empty in the target however full it is in
                # the source: copying nurture actions leaves `document_segments`
                # at 0 against 750,816, because no document segment was copied.
                # From the API this is indistinguishable from auto-sync having
                # missed rows -- attributing index rows to entities needs a join
                # the API does not expose -- so a verdict must not turn on it.
                # Failing here made a good copy read FAIL and would have hidden
                # a real shortfall in the noise.
                if not rows_n and src_rows and done:
                    note = "  <-- empty; expected if the copied type does not feed it"
                print(f"  {i['index_name']:<20} dst={rows_n or 0:>9,}  "
                      f"src={src_rows:>9,}{note}")
    except Exception as e:
        print(f"\ncould not read FTS index stats: {str(e)[:150]}")

    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}")
    if ok:
        print("Safe to consider deleting the originals — a separate, deliberate step.")
    return 0 if ok else 1


def _creation_times(api, space, graph, uris) -> dict:
    """Creation times for `uris`. Reads BOTH spaces and reports what it finds,
    so a URI absent from one of them is data, not an exception."""
    out = {}
    for q in fetch_entity_graph(api, space, graph, uris, allow_missing=True):
        if q.get("p") == f"<{CREATED_URI}>":
            out[q["s"]] = q["o"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("phase", choices=["plan", "copy", "verify"])
    ap.add_argument("--env", choices=["dev", "prod"], default="prod")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--dst", default=DEFAULT_DST)
    ap.add_argument("--src-graph", default=DEFAULT_GRAPH)
    ap.add_argument("--dst-graph", default=DEFAULT_GRAPH)
    ap.add_argument("--type", dest="type_uri", default=DEFAULT_TYPE)
    ap.add_argument("--months", default="2026-05,2026-06,2026-07")
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--parallel", type=int, default=20,
                    help="entity copies in flight at once")
    ap.add_argument("--batch", type=int, default=1,
                    help="entity graphs per request, within each worker")
    ap.add_argument("--page-size", type=int, default=200,
                    help="page size while enumerating in `plan`")
    ap.add_argument("--limit", type=int, default=0, help="stop after N entities")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="seconds between batches, to go easy on production")
    ap.add_argument("--report-every", type=int, default=10, help="progress every N batches")
    ap.add_argument("--sample", type=int, default=20, help="entity graphs to diff in verify")
    ap.add_argument("--plan-sample", type=int, default=30,
                    help="entity graphs sampled in `plan` to size the copy")
    ap.add_argument("--sample-seed", type=int, default=7)
    ap.add_argument("--stop-on-error", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-restamp", action="store_true",
                    help="proceed against a server without the preserve flag; "
                         "every copied entity WILL be dated now (calibration only)")
    a = ap.parse_args()

    _ALLOW_RESTAMP[0] = a.allow_restamp
    env = load_env()
    api = connect(a.env, env)
    root = Path(a.state_dir or (PROJECT_ROOT / ".archive_state" / f"{a.env}__{a.src}__{a.dst}"))
    st = State(root)
    print(f"state: {root}\n")

    if a.phase == "plan":
        return phase_plan(api, a, st) or 0
    if a.phase == "copy":
        return phase_copy(api, a, st)
    return phase_verify(api, a, st)


if __name__ == "__main__":
    sys.exit(main())
