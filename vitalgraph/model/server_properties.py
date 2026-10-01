"""The URIs of the properties the SERVER manages, in one place.

These are part of the API contract, not an implementation detail: a caller doing
an optimistic-concurrency write reads `hasObjectModificationDateTime` off the
entity it got back and sends it as `if_unmodified_since` (`issues/253`). So the
client needs the URI as much as the server does.

WHY THIS MODULE EXISTS. The definitions lived in
`vitalgraph.kg_impl.kg_server_properties`, which the client package deliberately
does not import — nothing under `vitalgraph/client/` reaches into `kg_impl`, and
a response model is the wrong place to start. The alternative was a second copy
in the client, and this repository has its own note on what that costs: the
client's success-status set is DERIVED from the server enum precisely because "a
hand-copied list is how the two drift". There were already two hardcoded copies
of the stamp URI in test scripts when this was written.

`kg_server_properties` re-exports these under its existing names, so nothing on
the server side changed.
"""
from __future__ import annotations

CREATION_TIME_URI = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
MODIFICATION_TIME_URI = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
STATUS_TYPE_URI = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
ENTITY_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"

__all__ = [
    "CREATION_TIME_URI",
    "MODIFICATION_TIME_URI",
    "STATUS_TYPE_URI",
    "ENTITY_TYPE_URI",
]
