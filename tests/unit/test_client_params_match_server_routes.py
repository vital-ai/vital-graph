"""The Python client must not send a query parameter the server ignores.

FastAPI DROPS an undeclared query parameter silently. So a client that sends a
filter the route does not declare gets back an UNFILTERED page and no error —
the wrong rows, looking exactly like the right ones.

Found live: `list_kgframes()` sent `parent_uri`, which `GET /api/graphs/kgframes`
does not declare, so filtering frames by parent returned every frame in the
graph. `/kgframes/kgslots` DOES declare it, which is why the bug survived
review — the parameter is real, just not on that route.

DIRECTION MATTERS. This asserts only that everything the client SENDS is
accepted. The reverse — a server parameter no client method exposes — is a
missing feature, not a wrong answer, and several are deliberate (`uri_list` is
served by `get_kgframes_by_uris`, not by the list method).

Parsed from source rather than by building the routers, which would need the
whole server dependency set for a check that is really about two signatures
agreeing.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _route_params(server_file: str, marker: str) -> set[str]:
    src = (REPO / "vitalgraph" / "endpoint" / server_file).read_text()
    i = src.index(marker)
    j = src.index("async def ", i)
    k = src.index("):", j)
    return set(re.findall(r"^\s{8,}(\w+)\s*:", src[j:k], re.M))


def _sent_params(client_file: str, method: str) -> set[str]:
    """Names passed to build_query_params(...) inside one client method."""
    src = (REPO / "vitalgraph" / "client" / "endpoint" / client_file).read_text()
    # The LAST occurrence: `@overload` stubs declare the same name with a `...`
    # body, and the implementation is the one that actually builds the request.
    i = src.rindex(f"async def {method}(")
    nxt = src.find("\n    async def ", i + 1)
    body = src[i:nxt if nxt != -1 else len(src)]
    call = body.index("build_query_params(")
    depth, end = 0, None
    for pos in range(call + len("build_query_params(") - 1, len(body)):
        if body[pos] == "(":
            depth += 1
        elif body[pos] == ")":
            depth -= 1
            if depth == 0:
                end = pos
                break
    assert end, f"could not parse build_query_params call in {method}"
    return set(re.findall(r"(\w+)\s*=", body[call:end]))


CASES = [
    ("kgframes_endpoint.py", '@self.router.get("/kgframes"',
     "kgframes_endpoint.py", "list_kgframes"),
    ("kgentities_endpoint.py", '@self.router.get("/kgentities"',
     "kgentities_endpoint.py", "list_kgentities"),
    # Both previously called `/api/graphs/kgframes/kgframes`, which is not a
    # registered route, with parameter names the real route does not declare.
    ("kgframes_endpoint.py", '@self.router.get("/kgframes"',
     "kgframes_endpoint.py", "get_child_frames"),
    ("kgframes_endpoint.py", '@self.router.get("/kgframes"',
     "kgframes_endpoint.py", "list_child_frames"),
]


def _kg_registered_routes() -> set[str]:
    """Paths registered by the kg* endpoint modules, which all mount under
    `/api/graphs`.

    SCOPED TO THOSE MODULES on purpose. Routers elsewhere are mounted under
    their own prefixes — the SPARQL ones register `/query` and are included at
    `/api/graphs/sparql` — so reconstructing a full path from source alone is
    guesswork. A test that guesses produces false alarms and gets deleted; this
    one checks the routers whose prefix is known and uniform.
    """
    import re
    paths = set()
    # GLOBBED, not enumerated: a hard-coded list missed `kgquery_endpoint.py`
    # (singular) and reported its `/kgqueries` route as dead.
    for f in (REPO / "vitalgraph" / "endpoint").glob("kg*_endpoint.py"):
        # Multi-line decorators are the common form, so match the path wherever
        # it falls after the router call rather than on the same line.
        for m in re.finditer(r"router\.(?:get|post|put|delete)\(\s*\n?\s*\"([^\"]+)\"",
                             f.read_text()):
            paths.add(m.group(1))
    return paths


def test_no_kg_client_method_calls_an_unregistered_route():
    """A client URL that no kg router registers is a guaranteed 404.

    `get_child_frames` and `list_child_frames` both called
    `/api/graphs/kgframes/kgframes`, which nothing registers, so neither had
    ever worked. Nothing failed loudly enough for anyone to notice.
    """
    import re
    registered = _kg_registered_routes()
    assert registered, "parsed no routes at all — the parser is broken"
    bad = []
    for f in (REPO / "vitalgraph" / "client" / "endpoint").glob("kg*.py"):
        for m in re.finditer(r'/api/graphs/(kg[A-Za-z0-9_/]*)"', f.read_text()):
            path = "/" + m.group(1)
            if path not in registered:
                bad.append(f"{f.name}: {path}")
    assert not bad, (
        "client methods target kg routes no router registers, so every call "
        "404s:\n  " + "\n  ".join(sorted(set(bad))))


@pytest.mark.parametrize("server_file,marker,client_file,method", CASES)
def test_every_parameter_the_client_sends_is_declared(
        server_file, marker, client_file, method):
    declared = _route_params(server_file, marker)
    sent = _sent_params(client_file, method)
    ignored = sent - declared
    assert not ignored, (
        f"{method}() sends {sorted(ignored)}, which "
        f"GET route `{marker.split('(')[1]}` does not declare. FastAPI drops "
        f"undeclared query parameters SILENTLY, so each of these is a filter "
        f"the caller believes is applied and the server never sees — an "
        f"unfiltered page returned as though it were filtered.")


def test_the_parent_uri_regression_stays_fixed():
    """The specific shape that was live, fixed on the SERVER side.

    `list_kgframes()` sends `parent_uri` and always did — the client was right
    and the route was missing it. The parameter is now declared and filters, so
    the assertion is that the client still SENDS it and the route still ACCEPTS
    it. Either half alone re-creates the silent drop.
    """
    src = (REPO / "vitalgraph" / "client" / "endpoint" / "kgframes_endpoint.py").read_text()
    i = src.rindex("async def list_kgframes(")
    nxt = src.find("\n    async def ", i + 1)
    body = src[i:nxt if nxt != -1 else len(src)]
    assert "parent_uri=parent_uri" in body, (
        "list_kgframes no longer sends parent_uri; a caller filtering by "
        "parent would silently get the whole graph")
    assert "parent_uri" in _route_params("kgframes_endpoint.py",
                                         '@self.router.get("/kgframes"'), (
        "GET /kgframes no longer declares parent_uri, so the client's value "
        "is dropped in transit")
