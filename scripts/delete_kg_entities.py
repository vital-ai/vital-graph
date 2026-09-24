#!/usr/bin/env python3
"""Delete KG entity graphs from a space, through the VitalGraph API.

The destructive half of `archive_kg_entities.py`. Same three phases, same
on-disk queue, same resumability -- and one rule that has no default:

    --require-copy-in SPACE   every entity is read back from SPACE and must
                              carry all of its quads before it is deleted here
    --no-copy-check           delete without that, stated deliberately

One of the two is mandatory. Deleting 43,783 entity graphs out of production
because a copy "looked fine" is the failure this guards against, and a default
either way is wrong: defaulting to the check makes the dangerous case quiet,
defaulting to no check makes the safe case opt-in.

    # remove a bad copy from the archive (nothing depends on it)
    python scripts/delete_kg_entities.py plan --env prod --space prod_kg_archive \\
        --uris-from .archive_state/<dir>/done.INVALID-restamped.jsonl
    python scripts/delete_kg_entities.py delete --env prod --space prod_kg_archive \\
        --no-copy-check

    # remove the originals once the archive holds them
    python scripts/delete_kg_entities.py plan --env prod --space prod_kg \\
        --months 2026-05,2026-06,2026-07
    python scripts/delete_kg_entities.py delete --env prod --space prod_kg \\
        --require-copy-in prod_kg_archive

SCOPED BY SPACE, NEVER BY GRAPH. Both spaces use the same graph URI
(`urn:prod_kg`), so a graph-scoped delete is ambiguous between them at the
API level -- it is exactly the mistake that would take the archive out along
with the source. `space_id` is required on every call here and is never
defaulted.

WHAT COUNTS AS PRESENT IN THE COPY. Every quad of the entity's graph in THIS
space must also be in the copy, ignoring differences the copy path is known to
introduce (`NORMALISED_ADDITIONS` in `archive_kg_entities.py`: the create path
stamps `hasKGFormType = Aspect` on entity-enclosed frames). Extra quads in the
copy are fine; a single missing one blocks the delete for that entity.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from archive_kg_entities import (  # noqa: E402
    Api, CREATED_URI, DEFAULT_GRAPH, DEFAULT_TYPE, ENTITY_TYPE_PRED,
    NORMALISED_ADDITIONS, State, connect, entity_uris_in_window,
    fetch_entity_graph, load_env, month_bounds)


def count(api, space, graph, type_uri, after=None, before=None) -> int:
    d = api.get("/api/graphs/kgentities/count", space_id=space, graph_id=graph,
                entity_type_uri=type_uri, created_after=after, created_before=before)
    n = d.get("count")
    return d.get("total_count", 0) if n is None else n


def read_uri_file(path: Path) -> list:
    """URIs from a JSONL done-log or a plain list, one per line."""
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                out.append(json.loads(line)["uri"])
                continue
            except Exception:
                pass
        out.append(line)
    return list(dict.fromkeys(out))


def copy_is_complete(api, a, uris):
    """Which of `uris` are fully present in the copy space.

    Returns (ok_uris, {uri: reason}). Absence of the copy space or of the
    entity is a refusal, not an error -- the caller must not delete either way.
    """
    ok, bad = [], {}
    # Absence on either side is the ANSWER here, not a fault.
    here = fetch_entity_graph(api, a.space, a.graph, uris, allow_missing=True)
    there = fetch_entity_graph(api, a.require_copy_in, a.graph, uris,
                               allow_missing=True)
    by_uri_here, by_uri_there = {}, {}
    for q in here:
        by_uri_here.setdefault(_owner(q["s"], uris), set()).add((q["s"], q["p"], q["o"]))
    for q in there:
        by_uri_there.setdefault(_owner(q["s"], uris), set()).add((q["s"], q["p"], q["o"]))
    for uri in uris:
        mine = by_uri_here.get(uri, set())
        theirs = by_uri_there.get(uri, set())
        if not mine:
            bad[uri] = "no entity graph in the source space"
            continue
        if not theirs:
            bad[uri] = f"absent from {a.require_copy_in}"
            continue
        missing = {t for t in mine - theirs if (t[1], t[2]) not in NORMALISED_ADDITIONS}
        if missing:
            bad[uri] = (f"{len(missing)} of {len(mine)} quads missing from "
                        f"{a.require_copy_in}, e.g. {list(missing)[0][1]}")
            continue
        ok.append(uri)
    return ok, bad


def _owner(subject: str, uris: list) -> str:
    """Attribute a subject to the entity whose graph it belongs to.

    Exact match or child URI -- never a substring split. Attributing a row to
    the wrong entity by splitting on a separator produced a believable but
    entirely wrong 4% figure once already.
    """
    s = subject.strip("<>")
    for u in uris:
        bare = u.strip("<>")
        if s == bare or s.startswith(bare + ":"):
            return u
    return subject


def delete_batch(api, a, uris) -> int:
    r = api._call(
        "DELETE",
        "/api/graphs/kgentities?" + _qs({
            "space_id": a.space, "graph_id": a.graph,
            "uri_list": ",".join(u.strip("<>") for u in uris),
            "delete_entity_graph": "true"}))
    status = str(r.get("status", "")).lower()
    if status not in ("deleted", "ok", "success", "not_found"):
        raise RuntimeError(f"delete status={r.get('status')}: {r.get('message')}")
    return r.get("deleted_count") or 0


def _qs(params):
    import urllib.parse
    return urllib.parse.urlencode(params)


# --------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------

def phase_plan(api, a, st: State):
    if a.uris_from:
        uris = read_uri_file(Path(a.uris_from))
        print(f"planning from {a.uris_from}: {len(uris):,} distinct URIs")
        rows = [{"uri": u, "month": "n/a"} for u in uris]
    else:
        months = [m.strip() for m in a.months.split(",") if m.strip()]
        print(f"planning: {a.type_uri}\n  delete from {a.space}  months={months}")
        rows = []
        for month in months:
            start, end = month_bounds(month)
            expected = count(api, a.space, a.graph, a.type_uri,
                             f"{start}T00:00:00", f"{end}T00:00:00")
            got, day = [], start
            while day < end:
                nxt = day + timedelta(days=1)
                u, _ = entity_uris_in_window(api, a.space, a.graph, a.type_uri,
                                             f"{day}T00:00:00", f"{nxt}T00:00:00",
                                             a.page_size)
                got.extend(u)
                day = nxt
            uniq = list(dict.fromkeys(got))
            print(f"  {month}: api count={expected:,}  enumerated={len(uniq):,}"
                  + ("" if len(uniq) == expected else "   <-- MISMATCH"))
            rows.extend({"uri": u, "month": month} for u in uniq)
    st.write_queue(rows)
    print(f"\nqueue written: {st.queue}  ({len(rows):,} rows)")
    print(f"next: delete --space {a.space} "
          f"{'--require-copy-in <space>' if not a.no_copy_check else '--no-copy-check'}")


def phase_delete(api, a, st: State):
    rows = st.read_queue()
    if not rows:
        print("queue is empty — run `plan` first")
        return 1
    done = st.done_uris()
    todo = [r for r in rows if r["uri"] not in done]
    print(f"DELETE from {a.space} (graph {a.graph})")
    print(f"  {len(rows):,} queued, {len(done):,} already deleted, {len(todo):,} to go")
    if a.require_copy_in:
        print(f"  safety: each entity must be fully present in {a.require_copy_in}")
    else:
        print("  safety: --no-copy-check — deleting WITHOUT verifying a copy exists")
    if a.limit:
        todo = todo[:a.limit]
        print(f"  --limit {a.limit}: this run will process {len(todo):,}")
    if a.dry_run:
        print("  DRY RUN — nothing will be deleted")
        if a.require_copy_in and todo:
            sample = [r["uri"] for r in todo[:a.batch]]
            ok, bad = copy_is_complete(api, a, sample)
            print(f"  copy check on the first {len(sample)}: {len(ok)} ok, {len(bad)} blocked")
            for u, why in list(bad.items())[:3]:
                print(f"     BLOCKED {u[:70]}: {why}")
        return 0

    units = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    started = time.time()
    tally = {"deleted": 0, "blocked": 0, "failed": 0, "entities": 0}
    lock = threading.Lock()
    stop = threading.Event()

    def work(unit):
        if stop.is_set():
            return
        uris = [r["uri"] for r in unit]
        try:
            if a.require_copy_in:
                uris, bad = copy_is_complete(api, a, uris)
                if bad:
                    with lock:
                        tally["blocked"] += len(bad)
                        tally["entities"] += len(bad)
                        for u, why in bad.items():
                            st.append(st.failed, {"uri": u, "blocked": why})
                        print(f"  BLOCKED {len(bad)}: {list(bad.values())[0][:110]}",
                              flush=True)
            if uris:
                delete_batch(api, a, uris)
                with lock:
                    tally["deleted"] += len(uris)
                    tally["entities"] += len(uris)
                    for u in uris:
                        st.append(st.done, {"uri": u, "ts": datetime.now().isoformat(
                            timespec="seconds")})
        except Exception as e:
            with lock:
                tally["failed"] += len(unit)
                tally["entities"] += len(unit)
                for r in unit:
                    st.append(st.failed, {"uri": r["uri"], "error": str(e)[:300]})
                print(f"  FAILED {unit[0]['uri'][:66]}: {str(e)[:150]}", flush=True)
            if a.stop_on_error:
                stop.set()
        if a.sleep:
            time.sleep(a.sleep)

    n_units = 0
    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        for fut in as_completed({pool.submit(work, u): u for u in units}):
            fut.result()
            n_units += 1
            if n_units % a.report_every == 0 or n_units == len(units):
                with lock:
                    el = time.time() - started
                    rate = tally["entities"] / el if el else 0
                    print(f"  {tally['entities']:,}/{len(todo):,}  "
                          f"deleted={tally['deleted']:,} blocked={tally['blocked']} "
                          f"failed={tally['failed']}  {rate:.1f} ent/s", flush=True)

    el = time.time() - started
    print(f"\ndone in {el/60:.1f}m: {tally['deleted']:,} deleted, "
          f"{tally['blocked']:,} blocked, {tally['failed']} failed")
    if tally["blocked"]:
        print(f"  blocked entities are in {st.failed} — they were NOT deleted")
    print("next: verify")
    return 1 if (tally["failed"] or tally["blocked"]) else 0


def phase_verify(api, a, st: State):
    rows = st.read_queue()
    done = st.done_uris()
    print(f"verify deletion from {a.space}\n")
    sample = [r["uri"] for r in rows if r["uri"] in done][:a.sample]
    still_there = 0
    for i in range(0, len(sample), 10):
        part = sample[i:i + 10]
        left = fetch_entity_graph(api, a.space, a.graph, part, allow_missing=True)
        owners = {_owner(q["s"], part) for q in left}
        still_there += len(owners)
        for u in owners:
            print(f"  STILL PRESENT: {u[:76]}")
    print(f"  sampled {len(sample)} deleted entities: {still_there} still return quads")
    total = count(api, a.space, a.graph, a.type_uri)
    print(f"  {a.type_uri} remaining in {a.space}: {total:,}")
    ok = still_there == 0
    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("phase", choices=["plan", "delete", "verify"])
    ap.add_argument("--env", choices=["dev", "prod"], default="prod")
    ap.add_argument("--space", required=True, help="space to DELETE FROM")
    ap.add_argument("--graph", default=DEFAULT_GRAPH)
    ap.add_argument("--type", dest="type_uri", default=DEFAULT_TYPE)
    ap.add_argument("--months", default="")
    ap.add_argument("--uris-from", help="JSONL done-log or plain URI list")
    ap.add_argument("--require-copy-in", help="space that must hold a complete copy")
    ap.add_argument("--no-copy-check", action="store_true",
                    help="delete without verifying a copy exists — say it out loud")
    ap.add_argument("--state-dir")
    ap.add_argument("--parallel", type=int, default=10)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--page-size", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--report-every", type=int, default=10)
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--stop-on-error", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.phase == "delete":
        if bool(a.require_copy_in) == bool(a.no_copy_check):
            ap.error("choose exactly one of --require-copy-in SPACE or --no-copy-check")
    if a.phase == "plan" and not (a.months or a.uris_from):
        ap.error("plan needs --months or --uris-from")

    env = load_env()
    api = connect(a.env, env)
    root = Path(a.state_dir or (PROJECT_ROOT / ".delete_state" / f"{a.env}__{a.space}"))
    st = State(root)
    print(f"state: {root}\n")

    if a.phase == "plan":
        return phase_plan(api, a, st) or 0
    if a.phase == "delete":
        return phase_delete(api, a, st)
    return phase_verify(api, a, st)


if __name__ == "__main__":
    sys.exit(main())
