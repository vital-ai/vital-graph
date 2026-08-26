"""The 422 handler must never be the thing that causes a 500.

Found 2026-08-16 by running the SPARQL 1.1 Protocol suite: 22 of its 34 standard
requests came back HTTP 500. All 22 went through one line in
`vitalgraph/main/main.py` — a custom `RequestValidationError` handler that
returned `{"detail": exc.errors()}` without `jsonable_encoder`.

When a request BODY fails validation, pydantic v2 puts the offending input in
`error["input"]`, and for a body whose Content-Type is not JSON that input is
raw `bytes`. `json.dumps` cannot serialise bytes, so the handler raised — and a
handler that raises produces a 500. A client's mistake was reported as a server
fault, on every endpoint that takes a model, for any non-JSON body.

WHY IT SURVIVED. The ordinary paths were all fine: a JSON body with a wrong
field returned 422, malformed JSON returned 422, a bad query parameter returned
422. Every test anyone would naturally write passed. The failure needed a body
whose CONTENT TYPE was not JSON, which no test sent until a spec suite did.

These tests call the helpers directly rather than through a live server, so they
run in CI without infrastructure — the live-server view is
`tests/conformance/test_dawg_protocol.py`.
"""

from __future__ import annotations

import json

import pytest

# From `validation_errors`, not `main`. These are pure functions, but `main`
# imports fastapi, starlette, uvicorn and (via vitalgraphapp_impl) torch — so
# importing them from there made a unit test of two string helpers depend on
# the whole server stack, and CI failed on whichever link was missing.
from vitalgraph.main.validation_errors import _describe_input, _safe_errors


def _serialisable(errors) -> str:
    """The assertion that actually matters: it survives json.dumps."""
    return json.dumps(_safe_errors(errors))


class TestNonJsonBodies:

    def test_utf8_bytes_body(self):
        """The 22 protocol requests all looked like this."""
        errors = [{
            "loc": ("body",), "msg": "Input should be a valid dictionary",
            "type": "model_attributes_type", "input": b"query=ASK%20%7B%7D",
        }]
        out = json.loads(_serialisable(errors))
        assert out[0]["input"] == "query=ASK%20%7B%7D"

    def test_utf16_body_does_not_raise(self):
        """`jsonable_encoder` alone is NOT enough, which is the second half.

        Its default rule for bytes is `o.decode()` — UTF-8 assumed. A UTF-16
        body still raised UnicodeDecodeError inside the handler written to stop
        the 500s, so the fix looked complete while two cases still returned 500.
        """
        errors = [{
            "loc": ("body",), "msg": "m", "type": "t",
            "input": "CLEAR NAMED".encode("utf-16"),
        }]
        out = json.loads(_serialisable(errors))
        assert "not valid UTF-8" in out[0]["input"]

    def test_arbitrary_binary_body(self):
        errors = [{"loc": ("body",), "msg": "m", "type": "t",
                   "input": b"\xff\xfe\x00\x01\x02"}]
        out = json.loads(_serialisable(errors))
        assert out[0]["input"] == "<5 bytes, not valid UTF-8>"

    def test_non_serialisable_ctx(self):
        """`ctx` can carry the original exception object."""
        errors = [{"loc": ("body",), "msg": "m", "type": "t",
                   "ctx": {"error": ValueError("boom")}}]
        out = json.loads(_serialisable(errors))
        assert "boom" in out[0]["ctx"]["error"]


class TestInputIsSummarisedNotReflected:

    def test_a_large_body_is_truncated(self):
        """Independent of encoding: do not echo an entire request body back.

        It can be megabytes, and it contains whatever the caller sent —
        including credentials they put in the wrong field.
        """
        errors = [{"loc": ("body",), "msg": "m", "type": "t",
                   "input": b"x" * 100_000}]
        out = json.loads(_serialisable(errors))
        assert len(out[0]["input"]) < 500
        assert out[0]["input"].endswith("...")

    def test_long_strings_truncate_too(self):
        assert _describe_input("y" * 10_000).endswith("...")
        assert len(_describe_input("y" * 10_000)) < 500

    def test_short_values_pass_through_unchanged(self):
        """Truncation must not damage the ordinary case.

        `loc`, `msg` and `type` are what a caller needs to fix the request; a
        handler that mangled them would trade a 500 for a useless 422.
        """
        errors = [{"loc": ("body", "query"), "msg": "Field required",
                   "type": "missing", "input": {"wrong": "field"}}]
        out = json.loads(_serialisable(errors))
        assert out[0]["input"] == {"wrong": "field"}
        assert out[0]["loc"] == ["body", "query"]
        assert out[0]["msg"] == "Field required"
        assert out[0]["type"] == "missing"


class TestHandlerContract:

    @pytest.mark.parametrize("value", [
        b"bytes", bytearray(b"bytearray"), "str", 42, 3.5, None, True,
        {"a": 1}, [1, 2], ("a", "b"),
    ])
    def test_every_input_shape_survives_serialisation(self, value):
        """A validation handler that can raise is worse than no handler.

        Whatever pydantic puts in `input`, the response must still be
        constructible — a 500 from the error path loses the diagnostic the
        caller needed AND misreports whose fault it was.
        """
        json.dumps(_safe_errors([{"loc": ("body",), "msg": "m",
                                  "type": "t", "input": value}]))

    def test_errors_without_an_input_key(self):
        json.dumps(_safe_errors([{"loc": ("query", "x"), "msg": "m", "type": "t"}]))

    def test_empty_error_list(self):
        assert _safe_errors([]) == []
