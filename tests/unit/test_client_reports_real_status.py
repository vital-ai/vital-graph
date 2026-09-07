"""The client must report the status the server returned, not a guess.

Every client endpoint method reported `status_code=500` for any failure, so a
caller branching on it could not tell "fix your input" from "the server is
broken". An invalid space id comes back as HTTP 400 — the API handler raises it
deliberately for validation errors, naming "space ID too long" in its own
comment — and the client relabelled it 500.

The server side was already hardened against this exact defect one layer up:
without its `except HTTPException: raise`, a deliberate 400 was re-reported as
500 and made the status code untrustworthy (issue 034).
"""
import pytest

from vitalgraph.client.endpoint.base_endpoint import http_status_of


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class _HttpStatusErrorLike(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.response = _Resp(status_code)


class TestHttpStatusOf:
    def test_it_reads_the_status_the_client_error_already_carries(self):
        # `_status_error` builds VitalGraphClientError(msg, status_code=...) from
        # the response, so the information was present and simply unused.
        from vitalgraph.client.vitalgraph_client import VitalGraphClientError
        assert http_status_of(VitalGraphClientError("bad", status_code=400)) == 400
        assert http_status_of(VitalGraphClientError("gone", status_code=404)) == 404

    def test_it_reads_the_status_off_an_httpx_style_error(self):
        assert http_status_of(_HttpStatusErrorLike(409)) == 409

    def test_a_transport_failure_still_reports_500(self):
        # No response means no status. "The server is broken" is the honest
        # answer here, and is the only case where 500 is invented.
        assert http_status_of(OSError("connection reset")) == 500

    def test_the_default_is_overridable(self):
        assert http_status_of(OSError("x"), default=503) == 503

    def test_a_zero_or_missing_status_falls_back(self):
        # Guards against an exception carrying status_code=None or 0, which
        # would otherwise be reported as a status of 0.
        class Odd(Exception):
            status_code = None
        assert http_status_of(Odd()) == 500


class TestEndpointsUseIt:
    """The helper only helps where it is actually called."""

    def test_no_endpoint_hardcodes_500_inside_an_except_block(self):
        import ast
        import pathlib

        root = (pathlib.Path(__file__).resolve().parents[2]
                / "vitalgraph" / "client" / "endpoint")
        offenders = []
        for f in sorted(root.glob("*_endpoint.py")):
            src = f.read_text()
            tree = ast.parse(src)
            lines = src.split("\n")
            for node in ast.walk(tree):
                if not (isinstance(node, ast.ExceptHandler) and node.name):
                    continue
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    if "status_code=500" in lines[ln - 1]:
                        offenders.append(f"{f.name}:{ln}")
        assert not offenders, (
            "these report a hardcoded 500 for a failure that carries a real "
            f"status, making the status code untrustworthy: {offenders[:6]}")
