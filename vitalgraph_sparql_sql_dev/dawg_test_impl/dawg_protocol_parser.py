"""Parse the SPARQL 1.1 Protocol manifest into runnable HTTP requests.

Unlike every other DAWG category, `protocol` does not ship machine-readable test
files. Each entry carries an `rdfs:comment` holding a markdown-ish description of
an HTTP exchange:

    #### Request

        POST /sparql/ HTTP/1.1
        Host: www.example
        Content-Type: application/sparql-query
        Content-Length: XXX

        ASK {}

    #### Response

        2xx or 3xx response
        Content-Type: application/sparql-results+xml or application/sparql-results+json

That is prose, and parsing prose is normally a bad bet. It is worth it here only
because the corpus is CLOSED — 34 entries, fixed, already written — so the
parser has to handle exactly what is in the file and nothing else, and
`assert_full_coverage()` fails loudly if it ever silently handles less.

WHAT IS DELIBERATELY NOT INFERRED. The expected response is read as a status
CLASS (`2xx or 3xx` vs `4xx`) and an optional set of acceptable content types.
The prose sometimes shows a body (`true`) but not in a form that distinguishes
"the response is the string true" from "the response encodes the boolean true"
in any of four serialisations, so bodies are not asserted. Guessing there would
manufacture failures that say nothing about the server.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pyoxigraph

logger = logging.getLogger(__name__)

MF = "http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"

PROTOCOL_TEST = f"{MF}ProtocolTest"

# The corpus is closed at 34 entries. A parser that silently started producing
# fewer would look exactly like a passing suite -- the failure this whole
# conformance effort exists to stop.
EXPECTED_ENTRY_COUNT = 34


@dataclass
class ProtocolTestCase:
    """One HTTP exchange the SPARQL 1.1 Protocol requires a server to handle."""

    name: str
    test_uri: str
    method: str
    path: str
    query_string: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    # "success" (2xx/3xx) or "client_error" (4xx).
    expect: str = "success"
    acceptable_content_types: List[str] = field(default_factory=list)
    raw_comment: str = ""

    @property
    def is_update(self) -> bool:
        """Whether this exercises the update half of the protocol.

        Read off the ENTRY NAME rather than sniffed from the body, because
        `bad_update_missing_form_type` has no parseable update in it at all --
        that is the point of the case.
        """
        return "update" in self.name


def parse_protocol_manifest(manifest_path: Path) -> List[ProtocolTestCase]:
    """Parse `protocol/manifest.ttl` into runnable cases."""
    if not manifest_path.exists():
        logger.warning("Protocol manifest not found: %s", manifest_path)
        return []

    store = pyoxigraph.Store()
    with open(manifest_path, "rb") as f:
        store.load(f, pyoxigraph.RdfFormat.TURTLE, base_iri=f"file://{manifest_path}")

    cases: List[ProtocolTestCase] = []
    for quad in store.quads_for_pattern(
        None,
        pyoxigraph.NamedNode(f"{RDF}type"),
        pyoxigraph.NamedNode(PROTOCOL_TEST),
        None,
    ):
        subject = quad.subject
        uri = subject.value
        name = _literal(store, subject, f"{MF}name") or uri.split("#")[-1]
        comment = _literal(store, subject, f"{RDFS}comment") or ""

        parsed = _parse_comment(comment)
        if parsed is None:
            logger.warning("Could not parse protocol entry %s", uri)
            continue

        method, path, qs, headers, body, expect, content_types = parsed
        cases.append(ProtocolTestCase(
            name=uri.split("#")[-1],
            test_uri=uri,
            method=method,
            path=path,
            query_string=qs,
            headers=headers,
            body=body,
            expect=expect,
            acceptable_content_types=content_types,
            raw_comment=comment,
        ))

    cases.sort(key=lambda c: c.name)
    return cases


def assert_full_coverage(cases: List[ProtocolTestCase]) -> None:
    """Fail if the parser stopped understanding part of the manifest.

    A prose parser degrades quietly: one reformatted entry and it yields 33
    cases instead of 34, every one of them passing. This is the guard that makes
    that loud.
    """
    if len(cases) != EXPECTED_ENTRY_COUNT:
        raise AssertionError(
            f"Parsed {len(cases)} protocol entries, expected "
            f"{EXPECTED_ENTRY_COUNT}. The manifest is prose; a parser that "
            f"quietly handles fewer entries looks identical to a passing suite."
        )
    unparsed = [c.name for c in cases if not c.method or not c.path]
    if unparsed:
        raise AssertionError(f"Entries with no request line: {unparsed}")


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------

_REQUEST_LINE = re.compile(
    r"^(GET|POST|PUT|DELETE|HEAD|PATCH)\s+(\S+)(?:\s+HTTP/[\d.]+)?\s*$"
)
_HEADER_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):\s*(.*)$")


def _parse_comment(comment: str):
    if "#### Request" not in comment:
        return None

    after = comment.split("#### Request", 1)[1]
    if "#### Response" in after:
        request_block, response_block = after.split("#### Response", 1)
    else:
        request_block, response_block = after, ""

    method = path = None
    query_string = ""
    headers: Dict[str, str] = {}
    body_lines: List[str] = []
    seen_blank_after_headers = False

    for raw in request_block.splitlines():
        line = raw.strip()
        if not line:
            # The blank line after the request line and headers starts the body.
            # Only counts once we HAVE a request line -- the block opens with a
            # blank line of its own.
            if method is not None:
                seen_blank_after_headers = True
            continue

        if method is None:
            m = _REQUEST_LINE.match(line)
            if m:
                method = m.group(1)
                target = m.group(2)
                path, _, query_string = target.partition("?")
            continue

        if not seen_blank_after_headers:
            m = _HEADER_LINE.match(line)
            if m:
                key, value = m.group(1), m.group(2)
                # Content-Length is shown as a placeholder; the client computes
                # the real one, and sending "XXX" would be a transport error
                # rather than a conformance result.
                if key.lower() != "content-length":
                    headers[key] = value
                continue
            # A non-header line before any blank line is still body text.
            seen_blank_after_headers = True

        body_lines.append(raw.strip())

    if method is None:
        return None

    body = "\n".join(body_lines).strip() or None

    expect = "client_error" if re.search(r"\b4xx\b", response_block) else "success"

    content_types: List[str] = []
    ct_match = re.search(r"Content-Type:\s*(.+)", response_block)
    if ct_match:
        # "a, b, c, or d" / "a or b"
        raw_types = re.split(r",|\bor\b", ct_match.group(1))
        content_types = [t.strip() for t in raw_types if "/" in t]

    return method, path, query_string, headers, body, expect, content_types


def _literal(store, subject, predicate_uri: str) -> Optional[str]:
    for quad in store.quads_for_pattern(
        subject, pyoxigraph.NamedNode(predicate_uri), None, None
    ):
        obj = quad.object
        return obj.value if hasattr(obj, "value") else str(obj)
    return None
