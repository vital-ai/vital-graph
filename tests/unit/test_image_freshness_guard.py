"""The stale-image guard must fail loudly, and must not fail for other reasons.

`issues/108`. The guard's value is entirely in what it does when things are NOT
normal, so those are the paths tested: a mismatch, a missing container, and the
escape hatch. A guard that passes quietly in any of them is the defect it exists
to catch, one level up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.shared import image_freshness as F
from tests.shared.image_freshness import ImageStale, diff


class TestTheDiffIsPerFileAndDirectional:
    """A single tree hash would say "stale" and nothing else. The three
    categories are what make the failure actionable: a changed file means
    rebuild, a file only in the tree was never built, a file only in the image
    was deleted since."""

    def test_changed_is_reported(self):
        assert diff({"a.py": "1"}, {"a.py": "2"}) == ([], [], ["a.py"])

    def test_only_in_tree_is_reported(self):
        assert diff({"a.py": "1"}, {}) == (["a.py"], [], [])

    def test_only_in_image_is_reported(self):
        assert diff({}, {"a.py": "1"}) == ([], ["a.py"], [])

    def test_identical_is_empty(self):
        assert diff({"a.py": "1"}, {"a.py": "1"}) == ([], [], [])


class TestItFailsRatherThanSkips:

    def test_a_mismatch_raises_and_names_the_files(self, monkeypatch):
        monkeypatch.setattr(F, "_local", lambda root: {"db/gen.py": "aaa"})
        monkeypatch.setattr(F, "_in_container", lambda c: {"db/gen.py": "bbb"})
        with pytest.raises(ImageStale) as exc:
            F.check("http://localhost:8002", Path("/repo"))
        msg = str(exc.value)
        assert "db/gen.py" in msg, "an opaque 'stale' is another red to ignore"
        assert "docker compose" in msg, "it must say how to fix it"

    def test_an_unreachable_container_on_a_local_target_raises(self, monkeypatch):
        """'Docker is not here, so pass' makes the guard a no-op exactly where
        nobody is looking. Something IS serving :8002; not knowing what it is
        makes a green run meaningless, not acceptable."""
        monkeypatch.setattr(F, "_in_container", lambda c: None)
        monkeypatch.setattr(F, "_local", lambda root: {})
        with pytest.raises(ImageStale) as exc:
            F.check("http://localhost:8002", Path("/repo"))
        assert "could not be reached" in str(exc.value)

    def test_a_match_passes(self, monkeypatch):
        monkeypatch.setattr(F, "_local", lambda root: {"a.py": "1"})
        monkeypatch.setattr(F, "_in_container", lambda c: {"a.py": "1"})
        F.check("http://localhost:8002", Path("/repo"))


class TestWhatIsDeliberatelyExempt:

    def test_a_remote_target_is_not_checked(self, monkeypatch):
        """A remote stack builds its image from the commit under test, and this
        working tree may not even be that commit."""
        def _boom(*a, **k):
            raise AssertionError("must not probe for a remote target")
        monkeypatch.setattr(F, "_in_container", _boom)
        monkeypatch.setattr(F, "_local", _boom)
        F.check("https://staging.example.invalid", Path("/repo"))

    def test_the_escape_hatch_still_reports(self, monkeypatch, capsys):
        """Going quiet would reproduce the defect one level up: a run that
        passes while testing something other than what it names."""
        monkeypatch.setenv(F.ALLOW_STALE, "1")
        monkeypatch.setattr(F, "_local", lambda root: {"db/gen.py": "aaa"})
        monkeypatch.setattr(F, "_in_container", lambda c: {"db/gen.py": "bbb"})
        F.check("http://localhost:8002", Path("/repo"))
        assert "differs from the working tree in 1 file" in capsys.readouterr().out


class TestTheAlgorithmIsSentNotShipped:

    def test_the_hasher_is_a_literal_string(self):
        """If it were imported inside the container it would be the STALE copy,
        so changing the hasher would produce a mismatch that is not staleness —
        and a guard that cries wolf gets disabled."""
        assert isinstance(F._HASHER, str)
        assert "hashlib" in F._HASHER

    def test_only_the_shipped_package_is_watched(self):
        """Editing tests/ or scripts/ needs no rebuild; flagging them would
        train people to ignore this."""
        assert F.PACKAGE == "vitalgraph"
