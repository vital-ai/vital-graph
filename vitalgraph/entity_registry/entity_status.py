"""Single source of truth for entity-registry status vocabularies.

`status` columns are enforced in code, not (historically) by the schema. This
module centralizes the allowed set per table so validation, the DB CHECK
constraints, and query filters all agree — Phase 1 of
`status_vocabulary_standardization_plan.md`.

Two shapes exist:
- `entity` is a multi-state lifecycle.
- The other seven are binary (active vs. a single terminal "gone" word). That
  word is **`retracted`** across all seven, unified by the standardization
  migration (previously `entity_category_map` / `entity_location` /
  `entity_location_category_map` used `removed`).
"""

# Individual status values, for use in SQL filters (f-stringed in) so the words
# are never spelled as bare literals scattered across queries.
ACTIVE = 'active'
INACTIVE = 'inactive'
MERGED = 'merged'
DELETED = 'deleted'
RETRACTED = 'retracted'

# Entity lifecycle.
ENTITY_STATUSES = (ACTIVE, INACTIVE, MERGED, DELETED)

# Terminal "gone" word for the binary tables.
BINARY_ACTIVE = 'active'
BINARY_GONE = 'retracted'
BINARY_STATUSES = (BINARY_ACTIVE, BINARY_GONE)

# Allowed status set per table. The CHECK constraints and the code validators
# both derive from this map, so a fourth word cannot be introduced by accident.
STATUS_SETS = {
    'entity': ENTITY_STATUSES,
    'entity_identifier': BINARY_STATUSES,
    'entity_alias': BINARY_STATUSES,
    'entity_relationship': BINARY_STATUSES,
    'entity_same_as': BINARY_STATUSES,
    'entity_category_map': BINARY_STATUSES,
    'entity_location': BINARY_STATUSES,
    'entity_location_category_map': BINARY_STATUSES,
}
