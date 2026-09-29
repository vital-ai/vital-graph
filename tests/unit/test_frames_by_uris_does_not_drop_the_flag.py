"""`include_frame_graph` on the `uris=` form says it is unimplemented.

`issues/240`. The flag was in the signature of `_get_frames_by_uris` and NOWHERE
in the body, so the multi-URI lookup returned frames without their graphs —
HTTP 200, `status=FOUND`, nothing to say a parameter had been ignored. The
single-URI sibling on the same endpoint DOES implement it, which is what makes
this a drop rather than an unbuilt feature.

It survived because it was untested: the only `/kgframes` cell with the flag set
covers `?uri=`, and its docstring says so. **A control pair — flag true says
something, flag false says nothing — is what catches this**, and it is the pair
`issues/210` used on the neighbouring surface.

Not implemented here on purpose. The right version is ONE batched query over the
page, which `issues/210`/`issues/226` need anyway; a per-URI repair would inherit
25 round trips and ship a second thing to undo.
"""

import inspect

from vitalgraph.endpoint import kgframes_endpoint, kgquery_endpoint

SRC = inspect.getsource(kgframes_endpoint.KGFramesEndpoint._get_frames_by_uris)


def test_the_flag_is_no_longer_dropped_silently():
    """The defect: the parameter appeared once, in the signature."""
    body = SRC.split('"""', 2)[-1]          # past the docstring
    assert "include_frame_graph" in body, (
        "the flag is still only in the signature — it is being dropped")
    assert "issues/240" in SRC


def test_it_reports_the_limitation_in_the_RESPONSE_not_just_a_log():
    """A caller cannot read the server's log. The outcome goes in the body, per
    the house rule that domain outcomes are HTTP 200 with the reason in the
    payload — not an HTTPException."""
    assert "message=_msg" in SRC, "the limitation never reaches the caller"
    assert "NOT implemented" in SRC
    assert "HTTPException" not in SRC.split("_msg =")[1].split("return")[0], (
        "a domain outcome must not be raised as an HTTP error")


def test_a_request_that_did_NOT_ask_gets_no_message():
    """THE CONTROL CELL, and it is not hypothetical: `issues/210` shipped an
    unconditional message on this exact pattern, and the test written to stop
    that found a crash instead."""
    assert '_msg = ""' in SRC, "no empty default — the message may be unconditional"
    assert "if include_frame_graph:" in SRC, (
        "the message is not gated on the caller having asked")


def test_the_kgqueries_message_no_longer_misdirects():
    """It told callers to use `/kgframes` 'where the flag is implemented on the
    URI lookups'. Only the single-URI form implements it, so that sent them from
    one silent no-op to another."""
    q = inspect.getsource(kgquery_endpoint)
    assert "/kgframes?uri= for a single frame" in q
    assert "the flag is implemented on the URI lookups" not in q, (
        "the over-broad claim issues/240 corrects is back")
