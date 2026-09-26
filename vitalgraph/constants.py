"""System-wide constants for VitalGraph."""

from enum import Enum

# ---------------------------------------------------------------------------
# System Spaces
# ---------------------------------------------------------------------------

SP_KG_TYPES = "sp_kg_types"
SP_KG_TYPES_GRAPH = f"urn:vitalgraph:{SP_KG_TYPES}:kg_types"

# System spaces that cannot be deleted by users.
PROTECTED_SPACES = frozenset({SP_KG_TYPES})


# ---------------------------------------------------------------------------
# Search Text Source Modes
# ---------------------------------------------------------------------------

class SearchTextSource(str, Enum):
    """What goes into the indexed search text for a mapping.

    Controls how the vector/FTS populator builds text for vectorization.
    """

    type_description = "type_description"
    """Index ONLY the KGType description from sp_kg_types (typical).
    Answers: 'What kind of thing is this?'"""

    properties = "properties"
    """Index selected properties from the subject only (typical).
    Answers: 'What does this thing contain?'"""

    properties_type = "properties_type"
    """Index subject properties + type description appended (rare).
    Combines content and type context."""

    default = "default"
    """Index all literal triples on the subject (legacy/fallback)."""


# ---------------------------------------------------------------------------
# Type URI → Description Property Mapping
# ---------------------------------------------------------------------------

# For each subject class, the property on the subject that holds its KGType URI,
# and the property on the KGType object that holds the type-specific description.

TYPE_URI_PROPERTIES = {
    "kgentity": "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType",
    "kgframe": "http://vital.ai/ontology/haley-ai-kg#hasKGFrameType",
    "kgdocument": "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentType",
    "kgslot": "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType",
}

# The description property a TYPE OBJECT carries, in `sp_kg_types`.
#
# `KGEntityType`, `KGFrameType` etc. are all `KGType` subclasses, and the ontology
# puts the description on `KGType` — one property for every type kind, not one per
# kind. `KGEntityType().kGraphDescription = "..."` serialises to exactly this.
#
# THIS IS NOT `TYPE_DESCRIPTION_PROPERTIES` BELOW, and conflating the two meant the
# type-description vector populator looked for a property a type object can never
# carry, found nothing, and skipped every subject — 0 vectors from a successful
# reindex (`issues/244`).
TYPE_GRAPH_DESCRIPTION_PROPERTY = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"

# The description properties an INSTANCE carries — a denormalised copy of its
# type's description, written onto the KGEntity/KGFrame itself so it can be sorted
# and filtered without a cross-space lookup (`fast_frame_prop_sort`,
# `sync_frame_prop_sort`, `kgtype_index_setup`).
#
# Do NOT use these to read a description OUT of `sp_kg_types`: the ontology gives
# `hasKGEntityTypeDescription` the domain `KGEntity`/`KGEntityMention`, not
# `KGEntityType`, and `hasKGDocumentTypeDescription` is not declared in the
# ontology at all. Use `TYPE_GRAPH_DESCRIPTION_PROPERTY` for a type object.
TYPE_DESCRIPTION_PROPERTIES = {
    "kgentity": "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription",
    "kgframe": "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription",
    "kgdocument": "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentTypeDescription",
    "kgslot": "http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription",
}
