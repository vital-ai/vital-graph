/**
 * Property URIs used as server-side sort keys.
 *
 * These must match the server allow-lists — an unlisted URI comes back as an
 * INVALID_REQUEST body (HTTP 200), not an exception:
 *   _FRAME_SORT_PROPERTIES / _SLOT_SORT_PROPERTIES  vitalgraph/model/kgframes_model.py
 *   _RELATION_SORT_PROPERTIES                       vitalgraph/model/kgrelations_model.py
 *
 * Ordering semantics for the sequence/index properties: values sort
 * numerically, and objects WITHOUT the property sort last in both directions
 * (they are not interleaved). See
 * planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md §3.
 */

export const NAME_PROPERTY = 'http://vital.ai/ontology/vital-core#hasName';
export const CREATED_PROPERTY = 'http://vital.ai/ontology/vital-aimp#hasObjectCreationTime';
export const MODIFIED_PROPERTY = 'http://vital.ai/ontology/vital#hasObjectModificationDateTime';

/** Order of a frame within its entity/parent frame. Integer, optional. */
export const FRAME_SEQUENCE_PROPERTY = 'http://vital.ai/ontology/haley-ai-kg#hasFrameSequence';

/** Order of a slot within its frame. Integer, optional. */
export const SLOT_SEQUENCE_PROPERTY = 'http://vital.ai/ontology/haley-ai-kg#hasSlotSequence';

/**
 * Order of a KG relation. Relations have no dedicated sequence property;
 * hasListIndex is inherited from VITAL_Edge and is the ordering key for them.
 */
export const LIST_INDEX_PROPERTY = 'http://vital.ai/ontology/vital-core#hasListIndex';

export const RELATION_TYPE_PROPERTY = 'http://vital.ai/ontology/haley-ai-kg#hasKGRelationType';
