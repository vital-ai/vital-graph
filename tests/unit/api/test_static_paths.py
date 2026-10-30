"""resolve_static_file — a catch-all route serves only files under its root.

`root / path` discards `root` when `path` is absolute, and the ASGI server has
already decoded `%2f` by the time the route sees the path. The route-level
cases send the raw request paths, because the encoding is the point.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.testclient import TestClient

from vitalgraph.api.static_paths import resolve_static_file


@pytest.fixture()
def tree(tmp_path):
    """A dist/ root with assets, and a secret beside it that must stay out."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("index")
    (root / "assets" / "app.js").write_text("js")
    (tmp_path / "secret.py").write_text("SECRET")
    return root


class TestResolve:
    @pytest.mark.parametrize("path", [
        "index.html", "assets/app.js", "assets/../index.html", "./index.html",
    ])
    def test_a_file_under_the_root_resolves(self, tree, path):
        assert resolve_static_file(tree, path) is not None

    def test_the_join_with_an_absolute_path_would_escape(self, tree):
        secret = tree.parent / "secret.py"
        assert (tree / str(secret)) == secret
        assert resolve_static_file(tree, str(secret)) is None

    @pytest.mark.parametrize("path", ["../secret.py", "assets/../../secret.py"])
    def test_dot_dot_cannot_leave_the_root(self, tree, path):
        assert resolve_static_file(tree, path) is None

    def test_a_sibling_sharing_the_root_prefix_is_outside(self, tree):
        sibling = tree.parent / "dist-private"
        sibling.mkdir()
        (sibling / "key").write_text("x")
        assert resolve_static_file(tree, "../dist-private/key") is None

    def test_a_symlink_out_of_the_root_is_refused(self, tree):
        (tree / "link").symlink_to(tree.parent / "secret.py")
        assert resolve_static_file(tree, "link") is None

    @pytest.mark.parametrize("path", ["", ".", "assets", "missing.js"])
    def test_a_directory_or_missing_file_is_not_a_file(self, tree, path):
        assert resolve_static_file(tree, path) is None

    @pytest.mark.parametrize("path", ["index.html\0.png", "a" * 5000])
    def test_a_path_no_filesystem_accepts_is_none_not_an_error(self, tree, path):
        assert resolve_static_file(tree, path) is None

    def test_a_symlink_loop_is_none_not_an_error(self, tree):
        (tree / "loop").symlink_to(tree / "loop")
        assert resolve_static_file(tree, "loop") is None


@pytest.fixture()
def client(tree):
    app = FastAPI()

    @app.get("/{path:path}")
    async def catch_all(path: str):
        found = resolve_static_file(tree, path)
        return FileResponse(found) if found else PlainTextResponse("spa")

    return TestClient(app)


class TestRoute:
    """Raw request paths, through a real path route."""

    @pytest.mark.parametrize("template", [
        "/{abs}",
        "//{abs}",
        "/%2f{abs}",
        "/%2F{abs}",
    ])
    def test_an_absolute_path_gets_the_spa_not_the_file(self, tree, client, template):
        secret = str(tree.parent / "secret.py").lstrip("/")
        for spelling in (secret, secret.replace("/", "%2f"), secret.replace("/", "/./")):
            response = client.get(template.format(abs=spelling))
            assert response.text == "spa"

    @pytest.mark.parametrize("path", [
        "/%2e%2e/secret.py", "/..%2fsecret.py", "/.%2e/secret.py",
    ])
    def test_an_encoded_dot_dot_gets_the_spa(self, client, path):
        assert client.get(path).text == "spa"

    def test_a_real_asset_is_still_served(self, client):
        assert client.get("/assets/app.js").text == "js"
