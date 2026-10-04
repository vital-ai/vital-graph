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

Every frame CREATE now follows it (`issues/256` item 3): a create refuses an
existing frame, so the methods that take an `operation_mode` are marked by the
mode they send (`replay_safe_mode`), and `create_child_frames`, which always
sends create, is not marked.
"""
import ast
import inspect

import pytest

from vitalgraph.client.endpoint import kgentities_endpoint, kgframes_endpoint
from vitalgraph.client.endpoint.base_endpoint import replay_safe_mode
from vitalgraph.client.retry import IDEMPOTENT_METHODS, FailureClass, classify_exception

REPLAY_SAFE = {
    "kgentities_endpoint": {
        "update_kgentities", "upsert_kgentities", "update_entity_only",
        "update_entity_frames"},
    "kgframes_endpoint": {
        "update_kgframes", "update_kgframes_with_slots",
        "update_frame_slots", "update_child_frames"},
}

# Marked by the mode they send: replayable for update/upsert/replace, not for
# create (`issues/256` item 3).
BY_MODE = {
    "kgentities_endpoint": {"create_entity_frames"},
    "kgframes_endpoint": {
        "create_kgframes", "create_kgframes_with_slots", "create_frame_slots"},
}

# Always send create, so never replayable.
NEVER = {
    "kgentities_endpoint": {"create_kgentities"},
    "kgframes_endpoint": {"create_child_frames"},
}

# Reads and counts that arrive as POST because the criteria go in the body. These
# opted in BEFORE this issue and are not its business; they are listed so the
# assertion below can tell "a read that was always replayable" from "a write
# somebody swept in".
READ_POSTS = {"query_entities", "query_frames", "batch_count_kgentities"}


def _posts_with_idempotent(module):
    """{method -> the `idempotent=` source text, or None} for every POST.

    "True" is an unconditional opt-in, "replay_safe_mode(operation_mode)" follows
    the mode, "False" or None is no opt-in.
    """
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
            value = next((ast.unparse(k.value) for k in node.keywords
                          if k.arg == "idempotent"), None)
            found[fn.name] = found.get(fn.name) or value
    return found


MODULES = {"kgentities_endpoint": kgentities_endpoint,
           "kgframes_endpoint": kgframes_endpoint}


class TestTheReplaySafeWritesOptIn:
    @pytest.mark.parametrize("modname", sorted(REPLAY_SAFE))
    def test_every_replay_safe_write_is_marked(self, modname):
        posts = _posts_with_idempotent(MODULES[modname])
        missing = [m for m in REPLAY_SAFE[modname] if posts.get(m) != "True"]
        assert not missing, f"replay-safe writes not marked idempotent: {missing}"

    @pytest.mark.parametrize("modname", sorted(BY_MODE))
    def test_a_write_that_takes_a_mode_is_marked_by_it(self, modname):
        posts = _posts_with_idempotent(MODULES[modname])
        wrong = {m: posts.get(m) for m in BY_MODE[modname]
                 if posts.get(m) != "replay_safe_mode(operation_mode)"}
        assert not wrong, f"not marked by mode: {wrong}"

    @pytest.mark.parametrize("modname", sorted(NEVER))
    def test_a_write_that_always_creates_is_not_marked(self, modname):
        # Safe for the DATA, not transparent for the CALLER: a replay answers
        # ALREADY_EXISTS, which reads as a failure for a write that succeeded.
        posts = _posts_with_idempotent(MODULES[modname])
        marked = {m: posts.get(m) for m in NEVER[modname]
                  if posts.get(m) not in (None, "False")}
        assert not marked, f"an always-create write is marked: {marked}"

    def test_no_delete_or_unknown_write_was_swept_in(self):
        # The flag is an assertion about a specific server path, so it must be
        # applied deliberately rather than broadly.
        for modname, module in MODULES.items():
            posts = _posts_with_idempotent(module)
            marked = {m for m, v in posts.items() if v not in (None, "False")}
            unexpected = (marked - REPLAY_SAFE[modname] - BY_MODE[modname]
                          - READ_POSTS)
            assert not unexpected, f"{modname}: unexpected opt-ins {unexpected}"


class TestTheModeDecides:
    @pytest.mark.parametrize("mode", ["update", "upsert", "replace", "UPDATE"])
    def test_a_replacing_mode_may_be_replayed(self, mode):
        assert replay_safe_mode(mode) is True

    @pytest.mark.parametrize("mode", ["create", "CREATE"])
    def test_a_create_may_not(self, mode):
        assert replay_safe_mode(mode) is False

    def test_an_enum_is_read_by_its_value(self):
        import enum

        class Mode(enum.Enum):
            CREATE = "create"
            UPSERT = "upsert"

        assert replay_safe_mode(Mode.CREATE) is False
        assert replay_safe_mode(Mode.UPSERT) is True


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
