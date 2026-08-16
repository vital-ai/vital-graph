"""Load-test data — space/graph ids, and the entity list `setup.py` generates.

WHY THIS FILE NO LONGER HOLDS THE LIST (issues/084). It used to BE the list:
`setup.py` rewrote it in place with the URIs it had just created. That made a
tracked source file the output of a command, with two consequences.

Running setup against an already-seeded space created nothing — the URIs are
derived from the org names, so every entity already existed — and the empty
result was then written over the file:

    SETUP COMPLETE — 0 entities ready        <- printed as success
    load_test_data.py | 83 +----------------

after which the driver refused to start with "run setup.py first", naming as the
cure the command that had caused it. Running it again did not help, and
recovering meant `git checkout` of a tracked file, which the message did not say.
And any local edit to the list was destroyed as a side effect of a setup run.

So the generated list now lives in an untracked JSON file beside this one, and
this module reads it. The tracked file is stable; the generated one is
regenerable and gitignored; `git status` stays clean after seeding.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOAD_TEST_SPACE_ID = "kg_load_test"
LOAD_TEST_GRAPH_ID = "urn:kg_load_test_graph"

# Written by setup.py, read here. Untracked — see .gitignore.
ENTITY_FILE = Path(__file__).parent / "load_test_entities.json"


def load_entity_data():
    """The entities setup.py recorded, or [] if it has not run.

    Returning [] rather than raising keeps `--cleanup` usable on a machine that
    never seeded, and the driver reports the missing-fixture case itself with a
    message that can name the real cause.
    """
    if not ENTITY_FILE.exists():
        return []
    try:
        with ENTITY_FILE.open() as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read %s: %s", ENTITY_FILE.name, exc)
        return []
    return data if isinstance(data, list) else []


ENTITY_DATA = load_entity_data()


def get_entity_uris():
    return [e["uri"] for e in ENTITY_DATA if "uri" in e]


def get_entity_names():
    return [e["name"] for e in ENTITY_DATA if "name" in e]
