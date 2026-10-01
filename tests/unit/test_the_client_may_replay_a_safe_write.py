"""Which POSTs the client may replay, and which it must not (`issues/253`).

A POST is not idempotent by method, so the retry policy refuses to replay one
after a post-send failure — `httpx.ReadTimeout` being the production case. That is
correct by default, and it is why ~190 timed-out frame writes a week became
UNCERTAIN WRITES nobody could resolve.

A write may opt in where the SERVER path makes it true, and that became true in
two steps: the subject-level write deletes the subjects it is about to write
before writing them, and every server-minted edge URI is now derived from its
endpoints rather than `uuid4()`. All nine production spaces were then checked to
carry the slim `(s,p,o,c)` quad key, so `ON CONFLICT DO NOTHING` really dedupes.

`create_kgentities` is the exception and stays off: its server path is a pure
INSERT behind an existence check, so a replay is safe for the DATA but answers
ALREADY_EXISTS — a reported failure for a write that in fact succeeded.
"""
import ast
import inspect

import pytest

from vitalgraph.client.endpoint import kgentities_endpoint, kgframes_endpoint
from vitalgraph.client.retry import IDEMPOTENT_METHODS, FailureClass, classify_exception

REPLAY_SAFE = {
    "kgentities_endpoint": {
        "update_kgentities", "update_entity_only",
        "create_entity_frames", "update_entity_frames"},
    "kgframes_endpoint": {
        "create_kgframes", "update_kgframes",
        "create_kgframes_with_slots", "update_kgframes_with_slots",
        "create_frame_slots", "update_frame_slots",
        "create_child_frames", "update_child_frames"},
}

# Reads and counts that arrive as POST because the criteria go in the body. These
# opted in BEFORE this issue and are not its business; they are listed so the
# assertion below can tell "a read that was always replayable" from "a write
# somebody swept in".
READ_POSTS = {"query_entities", "query_frames", "batch_count_kgentities"}


def _posts_with_idempotent(module):
    """{method -> bool} for every `_make_request('POST', …)` in the module."""
    tree = ast.parse(inspect.getsource(module))
    found = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if getattr(f, "attr", None) not in ("_make_request", "_make_typed_request"):
                continue
            verb = node.args[0].value if node.args and isinstance(
                node.args[0], ast.Constant) else None
            if verb != "POST":
                continue
            opted = any(k.arg == "idempotent" for k in node.keywords)
            found[fn.name] = found.get(fn.name, False) or opted
    return found


class TestTheReplaySafeWritesOptIn:
    @pytest.mark.parametrize("modname", sorted(REPLAY_SAFE))
    def test_every_replay_safe_write_is_marked(self, modname):
        module = {"kgentities_endpoint": kgentities_endpoint,
                  "kgframes_endpoint": kgframes_endpoint}[modname]
        posts = _posts_with_idempotent(module)
        missing = [m for m in REPLAY_SAFE[modname] if not posts.get(m)]
        assert not missing, f"replay-safe writes not marked idempotent: {missing}"

    def test_entity_create_is_deliberately_not_marked(self):
        # Safe for the DATA, not transparent for the CALLER: a replay answers
        # ALREADY_EXISTS, which reads as a failure for a write that succeeded.
        posts = _posts_with_idempotent(kgentities_endpoint)
        assert posts.get("create_kgentities") is False

    def test_no_delete_or_unknown_write_was_swept_in(self):
        # The flag is an assertion about a specific server path, so it must be
        # applied deliberately rather than broadly.
        for modname, module in (("kgentities_endpoint", kgentities_endpoint),
                                ("kgframes_endpoint", kgframes_endpoint)):
            posts = _posts_with_idempotent(module)
            marked = {m for m, v in posts.items() if v}
            unexpected = marked - REPLAY_SAFE[modname] - READ_POSTS
            assert not unexpected, f"{modname}: unexpected opt-ins {unexpected}"


class TestWhyItMatters:
    def test_a_read_timeout_is_post_send_and_so_needs_the_flag(self):
        import httpx

        # The production failure: the server may already have applied the write,
        # so the policy replays it only if the caller says it is safe.
        assert classify_exception(httpx.ReadTimeout("x")) is FailureClass.POST_SEND
        assert "POST" not in IDEMPOTENT_METHODS


class TestTheServerMessageSurvives:
    def test_the_two_frame_methods_no_longer_compose_over_it(self):
        # They reported "Created 0 frames" on a refused write and threw the
        # server's explanation away — and that explanation is the only place the
        # reason survives, since `raise_for_error` falls back to the message.
        # Slice the whole method — `update_entity_frames` has an error path with
        # its own `build_error_response` BEFORE the success path, so cutting at
        # the first one reads only half the body and proves nothing.
        src = inspect.getsource(kgentities_endpoint)
        for method in ("create_entity_frames", "update_entity_frames"):
            body = src[src.index(f"async def {method}"):]
            nxt = body.find("\n    async def ", 1)
            body = body[:nxt] if nxt > 0 else body
            assert 'response_data.get(\n                    "message"' in body \
                or 'response_data.get("message"' in body, method
