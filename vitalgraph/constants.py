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

TYPE_DESCRIPTION_PROPERTIES = {
    "kgentity": "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription",
    "kgframe": "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription",
    "kgdocument": "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentTypeDescription",
    "kgslot": "http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription",
}
