"""Compare a config document against a space — `issues/233` step 2.

Step 1 made a space's config readable. This makes it CHECKABLE: given a document
and a space, report what differs. The issue's reason for putting it before apply
is that it is what makes apply trustworthy — and that it is "the thing that would
have caught the `source_type` flip without anyone suspecting it", where
`source_type` moves from `default` to `properties` as a side effect of adding a
property, so replaying API calls in the obvious order does not reproduce a config.

A DIFF OF DOCUMENTS, NOT OF DATABASES. `export_space_config` already normalises —
no surrogate keys, no timestamps, stable order, JSONB parsed — so both sides
arrive comparable and this module needs no SQL of its own beyond one export. That
is why `diff_documents` is pure: the interesting logic is testable without a
database, and the DB-facing wrapper is four lines.

THREE THINGS IT MUST NOT CALL A DIFFERENCE
------------------------------------------
**Provenance.** `source_space_id`, `exported_at`, and the `absent_tables` /
`redacted` notes describe the export, not the config. Counting them would make
every cross-space diff dirty — and applying a document to a differently-named
space is the entire use case.

**A redacted secret.** A document exported with the default redaction carries
`__REDACTED__` where a key was. That is UNKNOWN, not different: reporting it as a
change would make every committed document diff dirty against the space it came
from, and reporting it as equal would hide a real rotation. It gets its own
bucket, `unknown`, so a caller can tell "I cannot see this" from "these agree".

**Field order and absent-vs-null.** Compared by value on a fixed key set, so a
missing key and an explicit `None` read the same. The databases genuinely produce
both for an optional column.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config_export import CONFIG_VERSION, _REDACTED, export_space_config

#: Document keys that describe the EXPORT rather than the config.
_PROVENANCE = ("version", "exported_at", "source_space_id", "absent_tables",
               "redacted")

#: section -> the fields that identify an item within it. Chosen to match the
#: export's ordering keys, so "same item" means the same thing in both places.
_IDENTITY: Dict[str, Tuple[str, ...]] = {
    "vector_indexes": ("index_name",),
    "fts_indexes": ("index_name",),
    "mappings": ("mapping_type", "type_uri", "index_name"),
    "fuzzy_mappings": ("mapping_type", "type_uri", "index_name"),
    "segmentation_config": ("document_type_uri", "segment_method_uri"),
}


def _key(item: Dict, fields: Tuple[str, ...]) -> Tuple:
    return tuple(item.get(f) for f in fields)


def _label(key: Tuple) -> str:
    return "/".join("" if k is None else str(k) for k in key)


def _compare_values(path: str, want: Any, have: Any,
                    changed: List[Dict], unknown: List[str]) -> None:
    """Record want-vs-have at *path*, treating a redacted want as unknown."""
    if want == _REDACTED:
        unknown.append(path)
        return
    if isinstance(want, dict) and isinstance(have, dict):
        for k in sorted(set(want) | set(have)):
            _compare_values(f"{path}.{k}", want.get(k), have.get(k),
                            changed, unknown)
        return
    if want != have:
        changed.append({"field": path, "document": want, "space": have})


def _diff_item(path: str, want: Dict, have: Dict,
               skip: Tuple[str, ...]) -> Tuple[List[Dict], List[str]]:
    changed: List[Dict] = []
    unknown: List[str] = []
    for field in sorted(set(want) | set(have)):
        if field in skip:
            continue
        _compare_values(f"{path}.{field}", want.get(field), have.get(field),
                        changed, unknown)
    return changed, unknown


def diff_documents(document: Dict[str, Any],
                   space_config: Dict[str, Any]) -> Dict[str, Any]:
    """What would change if *document* were applied to the space *space_config* describes.

    Pure. `document` is the desired state, `space_config` the observed one, and
    the direction is stated in every result key so a reader cannot get it
    backwards: `only_in_document` would be ADDED, `only_in_space` is EXTRA.
    """
    report: Dict[str, Any] = {"sections": {}, "unknown": [], "notes": []}

    doc_version = document.get("version")
    if doc_version != CONFIG_VERSION:
        # Reported, not raised: a caller comparing an archived document wants to
        # SEE this, and an apply wants to refuse on it.
        report["notes"].append(
            f"document version {doc_version!r} != current {CONFIG_VERSION!r}; "
            f"fields may be missing or mean something different")

    for section, identity in _IDENTITY.items():
        want_items = document.get(section) or []
        have_items = space_config.get(section) or []
        want_by = {_key(i, identity): i for i in want_items}
        have_by = {_key(i, identity): i for i in have_items}

        only_doc = [_label(k) for k in want_by.keys() - have_by.keys()]
        only_space = [_label(k) for k in have_by.keys() - want_by.keys()]
        changed: List[Dict] = []
        for k in sorted(want_by.keys() & have_by.keys()):
            c, u = _diff_item(f"{section}[{_label(k)}]", want_by[k], have_by[k],
                              skip=identity)
            changed.extend(c)
            report["unknown"].extend(u)

        if only_doc or only_space or changed:
            report["sections"][section] = {
                "only_in_document": sorted(only_doc),
                "only_in_space": sorted(only_space),
                "changed": changed,
            }

    # geo_config is a singleton, so "present on one side only" is not a list
    # membership question and the loop above cannot express it.
    want_geo, have_geo = document.get("geo_config"), space_config.get("geo_config")
    if want_geo is None and have_geo is None:
        pass
    elif want_geo is None or have_geo is None:
        report["sections"]["geo_config"] = {
            "only_in_document": ["geo_config"] if want_geo is not None else [],
            "only_in_space": ["geo_config"] if have_geo is not None else [],
            "changed": [],
        }
    else:
        c, u = _diff_item("geo_config", want_geo, have_geo, skip=())
        report["unknown"].extend(u)
        if c:
            report["sections"]["geo_config"] = {
                "only_in_document": [], "only_in_space": [], "changed": c}

    # `_PROVENANCE` is ignored BY CONSTRUCTION — this walks `_IDENTITY` and
    # `geo_config` and never reads those keys. The constant exists to name the
    # decision, and a test asserts it holds rather than trusting this comment.
    report["unknown"] = sorted(set(report["unknown"]))
    # DIFFERS IS ABOUT CONFIG ONLY. `unknown` deliberately does not set it: a
    # redacted secret is not evidence of a difference, and a verify that fails on
    # every committed document would simply stop being run.
    report["differs"] = bool(report["sections"])
    return report


async def diff_space_config(conn, space_id: str,
                            document: Dict[str, Any]) -> Dict[str, Any]:
    """Compare *document* against the live config of *space_id*. Read-only.

    Exported with `include_secrets=True` so a real provider value is available to
    compare against; whether the DOCUMENT can see it is the document's business,
    and that asymmetry is what `unknown` reports.
    """
    space_config = await export_space_config(conn, space_id,
                                             include_secrets=True)
    report = diff_documents(document, space_config)
    report["space_id"] = space_id
    report["source_space_id"] = document.get("source_space_id")
    return report
