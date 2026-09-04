#!/usr/bin/env python3
"""The Nurture-actions query shape, against a 50M-quad space.

THE SHAPE, from the production bench that started this incident: query entities
of one type, constrained by TWO frame criteria —

    A  a campaign URI   — COMMON, shared by many entities
    B  an SF lead id    — RARE, and ZERO for a lead that is new

and the reported failure was the zero case: "it should be finding 0 but instead
it times out". That is the direction problem exactly. The rare end is the one
`keep_top_n` drops, so before `issues/153` it priced as None and
`choose_direction` drove from the only end it could price — the common one —
scanning it to return nothing.

The equivalent here, on the loaded lead dataset:

    A  CompanyIdentityFrame / CompanyCountry  = "United States"   100,000 leads
    B  CompanyIdentityFrame / CompanyName     = <value>           1 or 0 leads

Run against the docker test stack with the space loaded.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

ENTITY_TYPE = "urn:acme:kg:entity:Lead"
FRAME = "urn:acme:kg:frame:NurtureInfoFrame"
SLOT_COMMON = "urn:acme:kg:slot:NurtureCampaignURI"
SLOT_RARE = "urn:acme:kg:slot:SFLeadId"
TEXT_CLASS = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
URI_CLASS = "http://vital.ai/ontology/haley-ai-kg#KGUriSlot"
HEAD_CAMPAIGN = "urn:acme:campaign:000"


def _crit(slot_type, value, klass=TEXT_CLASS):
    return {"frame_type": FRAME,
            "slot_criteria": [{"slot_type": slot_type,
                               "slot_class_uri": klass,
                               "value": value,
                               "comparator": "eq"}]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="nurture_shape_test")
    ap.add_argument("--graph", default="urn:nurture_shape_test")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--present", default=None,
                    help="a CompanyName that EXISTS (rare end matches)")
    a = ap.parse_args()

    os.environ.setdefault("LOCAL_CLIENT_SERVER_URL", "http://localhost:8002")
    os.environ.setdefault("LOCAL_CLIENT_AUTH_USERNAME", "admin")
    os.environ.setdefault("LOCAL_CLIENT_AUTH_PASSWORD", "admin")
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    client = VitalGraphClient()
    await client.open()
    try:
        common = _crit(SLOT_COMMON, HEAD_CAMPAIGN, URI_CLASS)
        shapes = [
            ("A  common + ABSENT rare  (the prod failure)",
             [common, _crit(SLOT_RARE, "ABSENT000000000")]),
            ("B  common + PRESENT rare (one match)",
             [common, _crit(SLOT_RARE, "SYN000000000")]),
            ("C  ABSENT rare only",
             [_crit(SLOT_RARE, "ABSENT000000000")]),
            ("D  common only (the end it would drive from)", [common]),
        ]

        print(f"\n{'shape':<48}{'ms (median of %d)' % a.repeats:>20}{'rows':>8}")
        for label, crit in shapes:
            times, rows, err = [], 0, None
            for _ in range(a.repeats):
                t0 = time.monotonic()
                try:
                    r = await client.kgqueries.query_entities(
                        space_id=a.space, graph_id=a.graph,
                        entity_type=ENTITY_TYPE, frame_criteria=crit,
                        page_size=1, offset=0)
                    rows = len(getattr(r, "entity_uris", None) or
                               getattr(r, "results", None) or [])
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"[:70]
                    break
                times.append((time.monotonic() - t0) * 1000)
            if err:
                print(f"{label:<48}{'ERROR':>20}   {err}")
            else:
                print(f"{label:<48}{statistics.median(times):>17,.0f} ms{rows:>8}")
    finally:
        try:
            await client.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
