"""Validation-error shaping, kept free of the server's import chain.

These are pure functions over stdlib types. They lived in `main.py`, which
imports fastapi, starlette, uvicorn and — through `vitalgraphapp_impl` — the
`heavy` extra, i.e. torch and transformers. So a unit test of two string
helpers could not run without installing several hundred megabytes, and CI
(which installs `.[dev]`) failed on `ModuleNotFoundError` for whichever link
in that chain happened to be missing: `itsdangerous`, then `uvicorn`.

Adding each missing package to `[dev]` would be chasing the chain. The helpers
simply do not belong behind it.

`main.py` re-exports both, so nothing that imported them from there breaks.
"""

from __future__ import annotations

from typing import Any, Dict, List

_MAX_ECHOED_INPUT = 200


def _safe_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Make pydantic's validation errors safe to serialise back to the client.

    Two problems with returning `exc.errors()` as-is, both of which showed up as
    500s rather than as anything that looked like a client error:

    1. `error["input"]` holds the raw request body when the body itself failed
       to parse. For a non-JSON Content-Type that is BYTES, and bytes are not
       JSON-serialisable. `jsonable_encoder` fixes the common case by decoding
       as UTF-8 -- and then raises UnicodeDecodeError on a body that is not
       UTF-8, which is the case the SPARQL Protocol suite tests deliberately.

    2. Echoing a whole request body back to the caller is not something to do by
       default regardless of encoding. It can be large, and it can contain
       whatever the caller sent, including credentials they put in the wrong
       field.

    So the input is summarised rather than reflected: decoded if it is text,
    described if it is not, and truncated either way. The error's `loc`, `msg`
    and `type` -- which are what a caller needs to fix the request -- are
    untouched.
    """
    safe: List[Dict[str, Any]] = []
    for error in errors:
        item = dict(error)
        if "input" in item:
            item["input"] = _describe_input(item["input"])
        # `ctx` can carry the original exception object, which is not
        # serialisable either.
        if "ctx" in item:
            item["ctx"] = {k: str(v) for k, v in (item["ctx"] or {}).items()}
        safe.append(item)
    return safe


def _describe_input(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            # The point of the non-UTF-8 protocol cases: say what it was rather
            # than fail trying to render it.
            return f"<{len(value)} bytes, not valid UTF-8>"
        return text[:_MAX_ECHOED_INPUT] + ("..." if len(text) > _MAX_ECHOED_INPUT else "")
    if isinstance(value, str) and len(value) > _MAX_ECHOED_INPUT:
        return value[:_MAX_ECHOED_INPUT] + "..."
    return value
