from __future__ import annotations

import os

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

CREATED = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
MODIFIED = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
# The ontology namespace comes from the environment, not this file: it is a
# deployment's own identifier and does not belong in the repository. Set
# VG_KG_NS to the namespace of the loaded space before running against it.
KG_NS = os.environ.get("VG_KG_NS", "urn:acme:kg")
ENTITY_TYPE = f"{KG_NS}:entity:NurtureAction"
MESSAGE_FRAME = f"{KG_NS}:frame:MessageFrame"
MESSAGE_SLOT = f"{KG_NS}:slot:MsgContent"
DRAFT_FRAME = f"{KG_NS}:frame:GeneratedMessageFrame"
DRAFT_SLOT = f"{KG_NS}:slot:GenMsgContent"


@dataclass(frozen=True)
class PortalFTSCase:
    name: str
    text: str
    populations: tuple[str, ...] = ("sent", "draft")
    date_property: Optional[str] = CREATED
    days: Optional[int] = 30
    sort_property: Optional[str] = CREATED
    sort_order: str = "desc"
    include_total_count: str = "yes"

    def lower_bound(self, now: Optional[datetime] = None) -> Optional[str]:
        if self.date_property is None or self.days is None:
            return None
        current = now or datetime.now(timezone.utc)
        floored = current.replace(minute=0, second=0, microsecond=0)
        return (floored - timedelta(days=self.days)).isoformat()


CASES = (
    PortalFTSCase(
        "fts-only-broad",
        "app",
        populations=("sent",),
        date_property=None,
        days=None,
        sort_property=None,
        include_total_count="no",
    ),
    PortalFTSCase(
        "fts-only-phrase",
        '"saved application"',
        populations=("sent",),
        date_property=None,
        days=None,
        sort_property=None,
        include_total_count="no",
    ),
    PortalFTSCase("broad-default", "app"),
    PortalFTSCase("multi-term-created", "saved application"),
    PortalFTSCase(
        "phrase-modified",
        '"saved application"',
        date_property=MODIFIED,
        days=30,
        sort_property=MODIFIED,
    ),
    PortalFTSCase(
        "or-exclusion-ascending",
        "plaid or reschedule -declined",
        sort_order="asc",
        include_total_count="no",
    ),
    PortalFTSCase(
        "sent-only",
        "saved",
        populations=("sent",),
        sort_property=MODIFIED,
    ),
    PortalFTSCase(
        "draft-only",
        "application",
        populations=("draft",),
        sort_property=MODIFIED,
    ),
    PortalFTSCase(
        "all-time",
        '"text me back"',
        date_property=None,
        days=None,
        sort_property=MODIFIED,
    ),
    PortalFTSCase(
        "absent",
        "zzzz_portal_absent_7f93c1",
        include_total_count="yes",
    ),
)
