"""The load-test fixture list is generated, not a tracked source file (issues/084).

`setup.py` used to rewrite `load_test_data.py` — a TRACKED module — with the URIs
it had just created. Against an already-seeded space it created nothing, because
the URIs derive from the org names and already existed, and then wrote that
nothing over the file:

    SETUP COMPLETE — 0 entities ready        <- printed as SUCCESS
    load_test_data.py | 83 +----------------

The driver then refused to start, advising "run setup.py first" — the command
that had just caused it, and which would do the same thing again. Recovery meant
`git checkout` of a tracked file, which nothing said.

Three properties are pinned here, because each was a separate part of the
failure: the tracked module is never written, an empty result is never recorded,
and absent is distinguishable from empty.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

LOAD_TEST_DIR = Path(__file__).resolve().parents[2] / "load_test_scripts"
TRACKED_MODULE = LOAD_TEST_DIR / "load_test_data.py"


@pytest.fixture
def load_test_data(monkeypatch):
    """Import the fixture module with `load_test_scripts` on the path."""
    monkeypatch.syspath_prepend(str(LOAD_TEST_DIR))
    module = importlib.import_module("load_test_data")
    return importlib.reload(module)


class TestTheTrackedFileIsNotTheOutput:

    def test_the_generated_list_is_a_separate_file(self, load_test_data):
        assert load_test_data.ENTITY_FILE != TRACKED_MODULE
        assert load_test_data.ENTITY_FILE.suffix == ".json"

    def test_the_generated_file_is_gitignored(self):
        """Otherwise seeding dirties the working tree on every run."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", "load_test_scripts/load_test_entities.json"],
            cwd=LOAD_TEST_DIR.parent, capture_output=True)
        assert result.returncode == 0, (
            "load_test_entities.json is not ignored; a seeding run would show "
            "up as a working-tree change"
        )

    def test_setup_writes_the_json_not_the_module(self):
        """The specific line that made a setup run destructive.

        `DATA_FILE` is what `_write_data` writes. It pointing at the tracked
        module IS the defect — checked in the source rather than by running
        setup, which needs a live server.
        """
        source = (LOAD_TEST_DIR / "setup.py").read_text()
        assert "DATA_FILE = ENTITY_FILE" in source
        assert 'DATA_FILE = _HERE / "load_test_data.py"' not in source

    def test_setup_no_longer_rewrites_a_python_module(self):
        """It used to emit `def get_entity_uris()` into the file it wrote."""
        source = (LOAD_TEST_DIR / "setup.py").read_text()
        assert "def get_entity_uris" not in source, (
            "setup.py is generating a Python module again"
        )


class TestAbsentIsNotEmpty:

    def test_missing_file_reads_as_no_entities(self, load_test_data, tmp_path,
                                               monkeypatch):
        monkeypatch.setattr(load_test_data, "ENTITY_FILE", tmp_path / "nope.json")
        assert load_test_data.load_entity_data() == []

    def test_unreadable_file_does_not_raise(self, load_test_data, tmp_path,
                                            monkeypatch):
        """A corrupt list must not take the driver down with a traceback."""
        bad = tmp_path / "load_test_entities.json"
        bad.write_text("{not json")
        monkeypatch.setattr(load_test_data, "ENTITY_FILE", bad)
        assert load_test_data.load_entity_data() == []

    def test_a_json_object_is_rejected_not_iterated(self, load_test_data, tmp_path,
                                                    monkeypatch):
        wrong = tmp_path / "load_test_entities.json"
        wrong.write_text('{"uri": "x"}')
        monkeypatch.setattr(load_test_data, "ENTITY_FILE", wrong)
        assert load_test_data.load_entity_data() == []

    def test_a_good_list_round_trips(self, load_test_data, tmp_path, monkeypatch):
        good = tmp_path / "load_test_entities.json"
        good.write_text(json.dumps([
            {"uri": "http://example.org/e/1", "name": "One"},
            {"uri": "http://example.org/e/2", "name": "Two"},
        ]))
        monkeypatch.setattr(load_test_data, "ENTITY_FILE", good)
        data = load_test_data.load_entity_data()
        assert len(data) == 2
        assert data[0]["uri"].endswith("/1")

    def test_entries_missing_a_uri_are_skipped_not_crashed_on(self, load_test_data,
                                                              tmp_path, monkeypatch):
        partial = tmp_path / "load_test_entities.json"
        partial.write_text(json.dumps([{"name": "no uri"}, {"uri": "http://x/1"}]))
        monkeypatch.setattr(load_test_data, "ENTITY_FILE", partial)
        load_test_data.ENTITY_DATA = load_test_data.load_entity_data()
        assert load_test_data.get_entity_uris() == ["http://x/1"]


class TestEmptyResultsAreNotRecorded:
    """Source-level, because the alternative needs a live server and a seeded
    space — the exact combination that made this hard to notice."""

    SOURCE = None

    def setup_method(self):
        self.SOURCE = (LOAD_TEST_DIR / "setup.py").read_text()

    def test_setup_refuses_to_write_an_empty_list(self):
        assert "if not entity_data:" in self.SOURCE
        assert "Not writing an empty" in self.SOURCE

    def test_a_failed_listing_is_distinguished_from_an_empty_space(self):
        """The two must not collapse: one means "no data", the other "no answer",
        and only the first should ever replace a good file."""
        assert "if entity_data is None:" in self.SOURCE
        assert "was NOT" in self.SOURCE

    def test_it_records_what_the_space_holds_not_what_it_created(self):
        assert "_entities_in_space" in self.SOURCE
        assert "entity_data = await _entities_in_space(client)" in self.SOURCE

    def test_failure_exits_non_zero(self):
        """It printed SETUP COMPLETE and returned 0 while destroying the list."""
        assert "sys.exit(1)" in self.SOURCE
        assert "SETUP FAILED" in self.SOURCE

    def test_success_line_no_longer_claims_completion_for_zero(self):
        assert "SETUP COMPLETE — %d entities ready" not in self.SOURCE
