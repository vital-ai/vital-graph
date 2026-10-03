"""Every fixture generator writes frame groupings and form types by the rule.

`issues/257`. The bulk-loaded spaces had no `hasFrameGraphURI` at all because
the generators that built them were wrong, and the one that did emit groupings
took a frame from its URI text, which grouped every nested child frame and its
slots under the ROOT: the shape found in production, written into a fixture.

The rule (decided 2026-10-03), the same one `kg_impl/frame_grouping.py`
applies on every write path:

- a KGFrame is grouped with ITSELF and carries an explicit `hasKGFormType`
  (option 2: the unset default classifies by grouping, so it is never relied on);
- a slot is grouped with the frame its Edge_hasKGSlot names, and that edge with
  its source frame;
- an Edge_hasKGFrame / Edge_hasEntityKGFrame carries NO grouping;
- every object in an entity's graph carries `hasKGGraphURI`.

The check reads only what the generator wrote: it rebuilds the frame/slot/edge
structure from the triples and compares the groupings against it.
"""

from __future__ import annotations

import collections
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VC = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"
TRIPLE = re.compile(r"^<([^>]*)> <([^>]*)> (.+) \.$")
TEMPLATES = REPO / "internal_data" / "lead_test_data"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def violations(lines) -> dict:
    vt, src, dst = {}, {}, {}
    fgu, kgg, ft = (collections.defaultdict(set) for _ in range(3))
    for line in lines:
        m = TRIPLE.match(line.strip())
        if not m or not m.group(3).startswith("<"):
            continue
        s, p, o = m.group(1), m.group(2), m.group(3)[1:-1]
        if p == VC + "vitaltype":
            vt[s] = o.rsplit("#", 1)[-1]
        elif p == VC + "hasEdgeSource":
            src[s] = o
        elif p == VC + "hasEdgeDestination":
            dst[s] = o
        elif p == KG + "hasFrameGraphURI":
            fgu[s].add(o)
        elif p == KG + "hasKGGraphURI":
            kgg[s].add(o)
        elif p == KG + "hasKGFormType":
            ft[s].add(o)
    owner = {dst[e]: src[e] for e, t in vt.items() if t == "Edge_hasKGSlot" and e in dst}
    # An entity's graph: the frames it attaches, their descendants, their slots
    # and the edges among them.
    scope = {dst[e] for e, t in vt.items() if t == "Edge_hasEntityKGFrame" and e in dst}
    grew = True
    while grew:
        grew = False
        for e, t in vt.items():
            if (t in ("Edge_hasKGFrame", "Edge_hasKGSlot") and src.get(e) in scope
                    and dst.get(e) not in scope):
                scope.add(dst[e])
                grew = True
    scope |= {e for e, t in vt.items() if t.startswith("Edge_") and src.get(e) in scope}
    scope |= {e for e, t in vt.items() if t == "Edge_hasEntityKGFrame"}

    bad = collections.Counter()
    for s, t in vt.items():
        want = ({s} if t == "KGFrame" else {src.get(s)} if t == "Edge_hasKGSlot"
                else {owner.get(s)} if t.endswith("Slot") else set()) - {None}
        if fgu[s] != want:
            bad[f"{t}: hasFrameGraphURI"] += 1
        if t == "KGFrame" and len(ft[s]) != 1:
            bad["KGFrame: hasKGFormType"] += 1
        if s in scope and not kgg[s]:
            bad[f"{t}: hasKGGraphURI"] += 1
    assert vt, "the generator wrote no typed objects"
    return dict(bad)


def _lines(out_dir: Path):
    return [ln for p in sorted(out_dir.glob("*.nt")) for ln in p.read_text().splitlines()]


def test_graph_generator(tmp_path):
    gen = _load("generate_graph_dataset")
    gen.generate(tmp_path, 40, 4, 2, 20260814, 5000,
                 attribute_slot_fraction=0.5, form_type_fraction=0.5)
    assert violations(_lines(tmp_path)) == {}


def test_relation_generator(tmp_path):
    gen = _load("generate_relation_dataset")
    gen.generate(tmp_path, 100, 20260810)
    assert violations(_lines(tmp_path)) == {}


def test_lead_generator_groups_by_structure_not_uri_text():
    # A nested child frame whose URI sits under its parent's: the case the
    # URI-text grouping got wrong. No templates needed.
    gen = _load("generate_lead_dataset")
    e = "urn:acme:lead:T1"
    root, child = f"{e}:frame:company:0", f"{e}:frame:company:0:frame:address:0"
    slot = f"{child}:slot:city"
    lines = [
        *gen._node(e, "KGEntity"),
        *gen._node(root, "KGFrame"), *gen._node(child, "KGFrame"),
        *gen._node(slot, "KGTextSlot"),
        *gen._edge(f"{e}:edge:entity_to_company_0", e, root, "Edge_hasEntityKGFrame"),
        *gen._edge(f"{root}:edge:to_address", root, child, "Edge_hasKGFrame"),
        *gen._edge(f"{child}:edge:to_slot_city", child, slot, "Edge_hasKGSlot"),
    ]
    out = lines + gen.entity_groupings(lines, e)
    assert violations(out) == {}
    assert f"<{slot}> <{KG}hasFrameGraphURI> <{child}> ." in out, (
        "the slot of a nested child frame must be grouped with the CHILD")


@pytest.mark.skipif(not TEMPLATES.is_dir(), reason="lead templates are in gitignored internal_data/")
def test_lead_generator_end_to_end(tmp_path):
    gen = _load("generate_lead_dataset")
    gen.generate(TEMPLATES, tmp_path, 10, 20260806, False, 5000, 0.5, 5)
    assert violations(_lines(tmp_path)) == {}
