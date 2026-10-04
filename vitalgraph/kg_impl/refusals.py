"""The base of every refusal that is the CALLER's to fix.

`issues/256`. A write or delete the contract does not allow — a slot with no
frame to belong to, an entity with members deleted alone, a frame of another
entity, an entity's frame named on `/kgframes`, a frame written onto an entity
that is gone — is answered INVALID_REQUEST in a 200, with `str(e)` as the
message, and nothing is written.

One base so a handler catches the family rather than each member. There were
three by the time this existed, threaded through the same handlers by hand, and
`tests/unit/test_a_refusal_reaches_the_caller.py` checks that every handler on a
refusal path lets it past.

Imports nothing from vitalgraph, so any module can import it without a cycle.
"""


class RequestRefused(ValueError):
    """A request the contract does not allow; nothing was written."""
