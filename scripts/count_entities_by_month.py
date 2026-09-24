#!/usr/bin/env python3
"""Count KG entities per calendar month, through the VitalGraph REST API.

Written for nurture actions (`urn:example:kg:entity:NurtureAction`), which is
the default `--type`, but the type URI is a plain argument so this works for any
entity type.

Counting happens server-side: one `GET /api/graphs/kgentities/count` per month
with `created_after`/`created_before` bounds. That matters on production, where
the RDS parameter group sets `statement_timeout=60s` -- a single grouped
aggregate over the whole type would be killed, while each month is its own
short statement.

The month range is discovered, not assumed: a binary search over
`created_before` finds the first month holding data, and over `created_after`
the last. Pass `--from`/`--to` to skip the search.

Every run checks that the months partition the unfiltered total and prints the
remainder explicitly, so a silently dropped bucket cannot be read as a real dip.

    python scripts/count_entities_by_month.py --env prod
    python scripts/count_entities_by_month.py --env prod --from 2026-05 --to 2026-09
    python scripts/count_entities_by_month.py --env dev --space prod_kg --csv out.csv
    python scripts/count_entities_by_month.py --env prod --date-field modified
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Defaults are PLACEHOLDERS, not a deployment's real identifiers — this
# repository does not carry those. Override per run with the flags, or set
# the VG_ARCHIVE_* environment variables once and omit them.
DEFAULT_TYPE = os.environ.get("VG_ARCHIVE_TYPE", "urn:example:kg:entity:NurtureAction")
DEFAULT_SPACE = os.environ.get("VG_ARCHIVE_SPACE", "prod_kg")
DEFAULT_GRAPH = os.environ.get("VG_ARCHIVE_GRAPH", "urn:prod_kg")
# Floor for the range search. No real record predates this; it only bounds the
# binary search, and anything below it still shows up in the unbucketed total.
SEARCH_FLOOR = (2000, 1)


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
    """Minimal VitalGraph API client with retry on transient server errors."""

    def __init__(self, base: str, user: str, password: str, retries: int = 3):
        self.base = base.rstrip("/")
        self.retries = retries
        self.token = self._login(user, password)
        self.calls = 0
        self.seconds = 0.0

    def _request(self, method, path, data, headers):
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode() or "{}")

    def _login(self, user, password):
        body = urllib.parse.urlencode({"username": user, "password": password}).encode()
        d = self._request("POST", "/api/login", body,
                          {"Content-Type": "application/x-www-form-urlencoded"})
        return d["access_token"]

    def get(self, path, **params):
        url = path + "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
        headers = {"Authorization": f"Bearer {self.token}"}
        last = None
        for attempt in range(self.retries):
            started = time.time()
            try:
                out = self._request("GET", url, None, headers)
                self.calls += 1
                self.seconds += time.time() - started
                return out
            except urllib.error.HTTPError as e:
                # 5xx here is a genuine server fault (this API reports domain
                # outcomes as HTTP 200), and in practice it is intermittent.
                if e.code < 500 or attempt == self.retries - 1:
                    raise
                last = e
                time.sleep(2 * (attempt + 1))
        raise last


# --------------------------------------------------------------------------
# month helpers
# --------------------------------------------------------------------------

def month_index(y: int, mo: int) -> int:
    return y * 12 + (mo - 1)


def from_index(idx: int) -> tuple:
    return idx // 12, idx % 12 + 1


def month_start(idx: int) -> str:
    y, mo = from_index(idx)
    return f"{y:04d}-{mo:02d}-01T00:00:00"


def month_label(idx: int) -> str:
    y, mo = from_index(idx)
    return f"{y:04d}-{mo:02d}"


def parse_month(text: str) -> int:
    y, _, mo = text.partition("-")
    return month_index(int(y), int(mo))


# --------------------------------------------------------------------------
# counting
# --------------------------------------------------------------------------

class Counter:
    def __init__(self, api: Api, space: str, graph: str, type_uri: str,
                 date_field: str, verbose: bool):
        self.api = api
        self.space = space
        self.graph = graph
        self.type_uri = type_uri
        self.after_key = f"{date_field}_after"
        self.before_key = f"{date_field}_before"
        self.verbose = verbose

    def count(self, after: str | None = None, before: str | None = None) -> int:
        params = {"space_id": self.space, "graph_id": self.graph,
                  "entity_type_uri": self.type_uri}
        if after:
            params[self.after_key] = after
        if before:
            params[self.before_key] = before
        d = self.api.get("/api/graphs/kgentities/count", **params)
        # The count endpoint returns `count`; the listing endpoint returns
        # `total_count`. Accept either so this survives a response-shape change.
        n = d.get("count")
        if n is None:
            n = d.get("total_count")
        if n is None:
            raise RuntimeError(f"no count in response: {d}")
        return n

    def active_years(self, first_year: int, last_year: int) -> list:
        """Years holding at least one record.

        A coarse pass before the month pass. Without it a handful of records
        carrying a bogus epoch-era date drags the start of the range back to
        the search floor and the run spends hundreds of calls counting empty
        months -- 343 calls where 39 would do. Counting a whole empty year
        costs the same as counting an empty month.
        """
        out = []
        for y in range(first_year, last_year + 1):
            n = self.count(after=f"{y:04d}-01-01T00:00:00",
                           before=f"{y + 1:04d}-01-01T00:00:00")
            if self.verbose:
                print(f"    ...{y}: {n:,}", file=sys.stderr)
            if n:
                out.append(y)
        return out


def main():
    ap = argparse.ArgumentParser(
        description="Count KG entities per month via the VitalGraph API")
    ap.add_argument("--env", choices=["dev", "prod"], default="prod")
    ap.add_argument("--space", default=DEFAULT_SPACE)
    ap.add_argument("--graph", default=DEFAULT_GRAPH)
    ap.add_argument("--type", dest="type_uri", default=DEFAULT_TYPE)
    ap.add_argument("--from", dest="first", help="first month, YYYY-MM")
    ap.add_argument("--to", dest="last", help="last month, YYYY-MM")
    ap.add_argument("--date-field", choices=["created", "modified"],
                    default="created")
    ap.add_argument("--csv", help="also write the table to this CSV path")
    ap.add_argument("--show-empty", action="store_true",
                    help="keep leading/trailing months with no records")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show range-search progress on stderr")
    a = ap.parse_args()

    env = load_env()
    if a.env == "dev":
        api = Api(env["LOCAL_CLIENT_SERVER_URL"], env["LOCAL_CLIENT_AUTH_USERNAME"],
                  env["LOCAL_CLIENT_AUTH_PASSWORD"])
    else:
        api = Api(env["PROD_CLIENT_SERVER_URL"], env["PROD_AUTH_ROOT_USERNAME"],
                  env["PROD_AUTH_ROOT_PASSWORD"])

    c = Counter(api, a.space, a.graph, a.type_uri, a.date_field, a.verbose)

    print(f"env={a.env}  space={a.space}  graph={a.graph}")
    print(f"type={a.type_uri}  date_field={a.date_field}")

    total = c.count()
    print(f"total entities of this type: {total:,}")
    if total == 0:
        print("nothing to count")
        return 0

    today = date.today()
    ceiling = month_index(today.year, today.month)

    if a.first and a.last:
        lo, hi = parse_month(a.first), parse_month(a.last)
    else:
        print("discovering range by year...")
        years = c.active_years(SEARCH_FLOOR[0], today.year)
        if not years:
            print("no entity carries this date field in range; nothing to bucket")
            return 0
        lo = parse_month(a.first) if a.first else month_index(years[0], 1)
        hi = parse_month(a.last) if a.last else min(month_index(years[-1], 12),
                                                    ceiling)
        print(f"years with data: {', '.join(str(y) for y in years)}")
    print(f"range: {month_label(lo)} .. {month_label(hi)} "
          f"({hi - lo + 1} months)\n")

    rows = []
    for idx in range(lo, hi + 1):
        n = c.count(after=month_start(idx), before=month_start(idx + 1))
        rows.append((month_label(idx), n))
        print(f"  {month_label(idx)}  {n:>9,}", flush=True)

    # Trim months with no data off both ends so the table shows the span that
    # actually holds records. The totals below still reconcile against the
    # unfiltered count, so nothing trimmed here can go unnoticed.
    if not a.show_empty:
        while rows and rows[0][1] == 0:
            rows.pop(0)
        while rows and rows[-1][1] == 0:
            rows.pop()
        if rows:
            lo, hi = parse_month(rows[0][0]), parse_month(rows[-1][0])

    # Re-read the total after the month pass. Production writes nurture actions
    # continuously, so a total taken before the buckets is already stale by the
    # time they finish -- reconciling against it reported a phantom missing row
    # when the only thing that happened was the current month growing.
    total_end = c.count()
    drift = total_end - total
    total = total_end

    counted = sum(n for _, n in rows)
    peak = max((n for _, n in rows), default=0)

    print(f"\n{'month':<9} {'count':>10}  {'share':>7}")
    print("-" * 46)
    for label, n in rows:
        bar = "#" * round(24 * n / peak) if peak else ""
        share = f"{100.0 * n / counted:5.1f}%" if counted else "    -"
        print(f"{label:<9} {n:>10,}  {share:>7}  {bar}")
    print("-" * 46)
    print(f"{'in range':<9} {counted:>10,}")

    # The months must partition the type's total. Anything left over carries a
    # date outside the printed range (or none at all) and is reported rather
    # than folded into a bucket -- a missing bucket would otherwise read as a
    # genuine dip in activity.
    remainder = total - counted
    print(f"{'outside':<9} {remainder:>10,}")
    print(f"{'total':<9} {total:>10,}")
    if drift:
        print(f"\n  note: the type grew by {drift:,} during this run "
              f"(live writes). Buckets are point-in-time, so the most recent "
              f"month undercounts by roughly that much.")
    if remainder:
        before = c.count(before=month_start(lo))
        after = c.count(after=month_start(hi + 1))
        undated = remainder - before - after
        print(f"\n  of the {remainder:,} outside the range: "
              f"{before:,} before {month_label(lo)}, "
              f"{after:,} after {month_label(hi)}, "
              f"{undated:,} with no usable {a.date_field} date")

    print(f"\n{api.calls} API calls, {api.seconds:.1f}s server time")

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["month", "count"])
            w.writerows(rows)
        print(f"wrote {a.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
