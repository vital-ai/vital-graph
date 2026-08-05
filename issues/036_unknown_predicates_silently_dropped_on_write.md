# Unknown Predicates Are Silently Dropped on Write

## Status: FIXED (2026-08-05) — warns; still does not reject

Items 1 and 3 done. Item 2 (`dropped_predicates` in the response) is
deliberately not done — see below.

### What it does now

```
WARNING quad_list_to_graphobjects: 2 predicate(s) not properties of KGDocument
        were dropped: http://vital.ai/ontology/haley-ai-kg#hasKGDocumentFileNode,
        http://vital.ai/ontology/haley-ai-kg#hasTotallyMadeUpProperty
```

Predicates are reported as **full URIs**. Abbreviating them would mean
splitting on a separator this code has no business assuming, and two namespaces
can share a local name. Class names come from the resolved Python class
(`cls.__name__`), not from the URI text.

The predicates are **still dropped**. This is a diagnostic, not a behaviour
change, for the reason argued below: the failure mode is silence, not
permissiveness, and rejecting would break callers relying on tolerance.

### How

`_allowed_property_uris(type_uri)` resolves the class through the VitalSigns
registry (`get_vitalsigns_class`) and reads `get_allowed_properties()`, cached
per type — a bulk write converts many subjects of the same few types.

It returns `None`, not an empty set, when the class cannot be resolved. `None`
means *cannot say*; an empty set would mean *nothing is allowed* and would
accuse every predicate on every custom type. Nothing is logged in that case.

### Item 3 is only partly delivered — deliberately

`_predicate_hint` names the cause when the dropped predicate **is itself a
registered class**:

```
... were dropped: http://vital.ai/ontology/haley-ai-kg#Edge_hasKGDocumentFileNode
    (Edge_hasKGDocumentFileNode is a class, not a property)
```

It does **not** fire for the literal input from issue 018. Writing
`hasKGDocumentFileNode` — the property-style name — is reported as dropped, but
with no "you meant the Edge class" nudge.

A first version did produce that nudge, by splitting the predicate URI and
synthesising `<namespace>Edge_<localname>` to look up. That was removed:
deriving one URI from another on the strength of a naming convention is
guessing dressed as resolution, and it breaks on any ontology that does not
follow the `Edge_` convention or uses a different separator. The hint now
resolves only the URI it is handed.

Restoring the nudge properly would need an ontology lookup relating a property
to its Edge class. Worth doing if the trap recurs; faking it with string
manipulation is not.

### Both paths, deliberately

`_warn_dropped_predicates` is called from the fast path *and* from the rdflib
fallback, which needed its own call and a small adapter
(`_subject_map_from_triples`) because it never builds a property map. Per the
correction above, they do not share a fix site — and the fallback runs only
after the fast path raised, which is the worst moment to lose a diagnostic.

### Item 2 not done

Threading `dropped_predicates` into `QuadResultsResponse` means carrying the
information up through the conversion utility, the space impl and the endpoint.
The log line already turns the debugging session described below into a grep,
which was the stated goal. Worth doing if a client ever needs to act on it
programmatically; noted rather than silently skipped.

### One thing this is not

An **unregistered class** already fails loudly — VitalSigns'
`get_vitalsigns_class` raises, the fast path falls back, and the fallback
raises too. The silent case is a *known* class with an *unknown predicate*, and
that is what this fix addresses.

### Verification

`tests/unit/test_dropped_predicate_warning.py` — 14 tests: the warning fires
and names the count and class; valid predicates produce **no** warning; a class
URI used as a predicate is named as a class while a property-style name is
reported without a guess; predicates appear as full URIs; the rdflib fallback
warns too; an unresolvable class stays silent; and the predicates are still
dropped rather than rejected.

Full local suite 2272 passed (three consecutive runs), `tests/api` 511 passed
against a rebuilt stack.

## Scope note: the conversion layer, not only the write path

The title says "on write" because that is where it bit, but the drop happens in
`quads → GraphObject` conversion, which the **read** path also uses via
`graphobjects_to_quad_list`. The round-trip in the reproduction is what makes
the loss visible at all. Anyone debugging a predicate missing from a read should
land here too.

## Summary

Quads whose predicate is not a valid property of the object's class are
discarded during `quads → GraphObject` conversion. No error, no warning, and the
write reports success. The caller believes the data was stored; it was not.

Reproduced against the current code:

```python
quads = [
    Quad(s="<urn:t:1>", p="<...#type>",                  o="<...haley-ai-kg#KGDocument>"),
    Quad(s="<urn:t:1>", p="<...vital-core#hasName>",     o='"Doc"'),
    Quad(s="<urn:t:1>", p="<...#hasKGDocumentFileNode>", o="<urn:file:1>"),   # an Edge CLASS, not a property
    Quad(s="<urn:t:1>", p="<...#hasTotallyMadeUpProperty>", o='"x"'),         # does not exist at all
]
objs = quad_list_to_graphobjects(quads)      # 1 object, no exception
graphobjects_to_quad_list(objs, "urn:g:1")   # → type, vitaltype, URIProp, hasName
```

**Four predicates in, two silently gone** — and the invented one is treated
exactly like the plausible-but-wrong one.

## Why it matters

This is not hypothetical. It cost real debugging time in `issues/018`:
`hasKGDocumentFileNode` is an **Edge class**
(`ai_haley_kg_domain.model.Edge_hasKGDocumentFileNode`), not a datatype property
on `KGDocument`. Writing it as a plain predicate was accepted by the API,
reported as created, and the link simply did not exist afterwards. The document
and the FileNode were both stored correctly; only the relationship vanished.
Nothing in the logs or the response indicated a problem — the only way to find
it was to query the stored object and notice a predicate missing.

The general failure mode: **a write that partially succeeds while reporting full
success**. Any client that sends a predicate the ontology does not recognise —
a typo, a renamed property, an ontology-version mismatch, or a class/property
confusion like the one above — loses that data with no signal.

## Where it happens

`quad_list_to_graphobjects` (`vitalgraph/utils/quad_format_utils.py:295`) builds
property maps and hands them to `GraphObject.from_property_maps` (VitalSigns).
That call keeps properties allowed on the resolved class and ignores the rest.
The drop is inside the library, but vitalgraph is where the information needed
to warn still exists: at `:428` the code has both `p_uri` and the subject's
`type_uri` in hand, immediately before the properties are handed over.

**Correction (verified 2026-08-05):** the fast path and the rdflib fallback do
**not** share a fix site. They use different VitalSigns entry points —

| path | entry point |
|---|---|
| fast (`_quad_list_to_graphobjects_fast`) | `GraphObject.from_property_maps` (`:450`) |
| fallback (`_quad_list_to_graphobjects_rdflib`) | `GraphObject.from_triples_list` (`:471`) |

— and the fallback never builds a property map at all, so a fix at `:428` would
miss it. Both drop the predicates identically (confirmed by running the
reproduction through each), so the *symptom* is shared; only the fix location
is not.

This matters more than it looks: the fallback is reached only when the fast
path **raises** (`:311-315`). A fast-path-only fix would go silent precisely
when something has already gone wrong — the worst moment to lose a diagnostic.
The check therefore belongs in the public entry point, which both paths return
through.

## Suggested fix

Warn — do not start rejecting. Rejecting would break any caller currently
relying on extra predicates being tolerated, and the failure mode here is
*silence*, not permissiveness.

1. After building each subject's property map and before
   `from_property_maps`, compare the requested predicates against what the
   resolved class accepts, and log the difference once per call:

   ```
   WARNING quad_list_to_graphobjects: 2 predicate(s) not properties of
           haley-ai-kg#KGDocument were dropped: hasKGDocumentFileNode,
           hasTotallyMadeUpProperty
   ```

2. Better, if cheap: surface the dropped predicates in the write response
   (`QuadResultsResponse`) as a `dropped_predicates` field, so an API client
   can see it without reading server logs. This fits the HTTP-200-domain-outcome
   convention — the write did succeed, just not completely.

3. Consider naming the likely cause when the predicate resolves to a known
   **class** rather than a property, since that is the trap that actually bit:
   *"`hasKGDocumentFileNode` is an Edge class — model it as an edge object with
   `hasEdgeSource`/`hasEdgeDestination`, not as a predicate."*

## Cost of not fixing

Every future ontology mismatch costs the same debugging session: notice data is
missing, disbelieve it, dump the stored quads, compare against what was sent,
then discover the predicate is not a property of the class. A single log line
turns that into a grep.

## Related

- `issues/018` — where this was found; the FileNode link is now modelled as a
  proper `Edge_hasKGDocumentFileNode`.
- `issues/022`, `issues/035` — same family of "operation reports success while
  doing nothing": a delete missing `graph_id` returning `no_op`, a cleanup using
  a parameter name the API ignores, a route form that 405s. The recurring
  lesson: **check that the thing you assume ran actually ran.**
