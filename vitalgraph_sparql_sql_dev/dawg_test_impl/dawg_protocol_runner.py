"""Issue the SPARQL 1.1 Protocol test requests against a live VitalGraph server.

WHAT THE MAPPING DOES, AND WHY IT IS DELIBERATELY GENEROUS. The manifest
addresses a bare `/sparql` endpoint with no authentication and no notion of a
dataset selector, because in the Protocol the ENDPOINT IS THE DATASET. Our
surface is `/api/graphs/sparql/query` and `/api/graphs/sparql/update`, needs a
`space_id` query parameter, and needs a bearer token.

So the runner adds the token and the `space_id` rather than reporting every case
as a failure on the address alone. That is a generous reading on purpose: it
measures what we would score if the routing question were already solved, which
is the only way to tell an addressing gap from a semantics gap. Where a case
still fails, the failure is about the protocol behaviour, not the URL.

The generosity is recorded per result in `mapping_notes` so no summary can imply
we serve `/sparql` when we do not.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .dawg_protocol_parser import ProtocolTestCase

logger = logging.getLogger(__name__)


@dataclass
class ProtocolResult:
    name: str
    status: str            # PASS | FAIL | ERROR
    http_status: Optional[int] = None
    content_type: str = ""
    detail: str = ""
    mapping_notes: List[str] = field(default_factory=list)


@dataclass
class ServerTarget:
    """Where to send the requests, and how to get past the parts of our surface
    the Protocol does not have."""
    base_url: str
    space_id: str
    token: Optional[str] = None
    query_path: str = "/api/graphs/sparql/query"
    update_path: str = "/api/graphs/sparql/update"


def run_protocol_case(case: ProtocolTestCase, target: ServerTarget) -> ProtocolResult:
    notes: List[str] = []

    path = target.update_path if case.is_update else target.query_path
    notes.append(f"{case.path} -> {path} (the Protocol has no dataset selector)")

    params = urllib.parse.parse_qsl(case.query_string, keep_blank_values=True)
    # Preserve REPEATED parameters. `bad_multiple_queries` is exactly two
    # `query=` values and collapsing them into a dict would turn the case under
    # test into a valid request that passes.
    params.append(("space_id", target.space_id))
    notes.append(f"space_id={target.space_id} added")

    url = f"{target.base_url}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = dict(case.headers)
    headers.pop("Host", None)          # set by the client
    headers.pop("User-agent", None)    # irrelevant to conformance
    if target.token:
        headers["Authorization"] = f"Bearer {target.token}"
        notes.append("bearer token added; the Protocol assumes no auth")

    data = None
    if case.body is not None:
        # `bad_query_non_utf8` and `bad_update_non_utf8` exist to check that a
        # server REJECTS a body that is not UTF-8. Encoding it as UTF-8 anyway
        # would quietly convert those two into ordinary valid requests.
        encoding = "utf-8"
        ct = headers.get("Content-Type", "")
        if "charset=UTF-16" in ct or "non_utf8" in case.name:
            encoding = "utf-16"
            notes.append("body sent as UTF-16, as the case requires")
        try:
            data = case.body.encode(encoding)
        except UnicodeEncodeError:
            data = case.body.encode("utf-8", errors="replace")

    req = urllib.request.Request(url, data=data, headers=headers, method=case.method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status = e.code
        content_type = e.headers.get("Content-Type", "") if e.headers else ""
    except Exception as e:  # transport failure -- not a conformance verdict
        return ProtocolResult(
            name=case.name, status="ERROR", detail=f"{type(e).__name__}: {e}",
            mapping_notes=notes,
        )

    return _judge(case, status, content_type, notes)


def _judge(case, status, content_type, notes) -> ProtocolResult:
    ok_class = (
        200 <= status < 400 if case.expect == "success" else 400 <= status < 500
    )

    if not ok_class:
        wanted = "2xx or 3xx" if case.expect == "success" else "4xx"
        extra = ""
        if case.expect == "client_error" and 200 <= status < 300:
            extra = (
                " -- the request is invalid and was ACCEPTED, so whatever "
                "happened next is undefined"
            )
        elif status >= 500:
            extra = " -- a 5xx for a client-supplied request is a server fault"
        return ProtocolResult(
            name=case.name, status="FAIL", http_status=status,
            content_type=content_type,
            detail=f"expected {wanted}, got {status}{extra}",
            mapping_notes=notes,
        )

    if case.expect == "success" and case.acceptable_content_types:
        base = content_type.split(";")[0].strip()
        if base not in case.acceptable_content_types:
            return ProtocolResult(
                name=case.name, status="FAIL", http_status=status,
                content_type=content_type,
                detail=(
                    f"status {status} is fine, but Content-Type {base!r} is not "
                    f"one of {case.acceptable_content_types}"
                ),
                mapping_notes=notes,
            )

    return ProtocolResult(
        name=case.name, status="PASS", http_status=status,
        content_type=content_type, mapping_notes=notes,
    )


def login(base_url: str, username: str, password: str) -> Optional[str]:
    """Get a bearer token, or None if the server does not need one."""
    body = urllib.parse.urlencode(
        {"username": username, "password": password}
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/api/login",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp).get("access_token")
    except Exception as e:
        logger.warning("Login failed: %s", e)
        return None
