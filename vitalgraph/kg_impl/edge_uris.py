"""Deterministic URIs for edges the SERVER mints.

`issues/253`. An edge between two objects the caller named is fully determined by
its endpoints, so its URI should be too. Four server-side mint sites used
`uuid.uuid4()` instead, and a random URI has two costs:

  * **The same write applied twice attaches the frame twice.** The subject-level
    delete in `update_subjects_graph` removes the quads of the subjects it is
    about to write; a fresh edge URI is not one of them, so the PREVIOUS edge
    survives and the entity ends up with two `Edge_hasEntityKGFrame` to one
    frame. Nothing else in the payload behaves this way — terms are
    content-addressed and the quad key is `(s,p,o,c)`.
  * **So the write cannot be retried.** A POST that times out may or may not
    have been applied, and the client (correctly) refuses to replay a
    non-idempotent request — `vitalgraph/client/retry.py`. That is the mechanism
    behind ~190 uncertain writes a week on production.

The form is NOT new: `_create_parent_child_edges` already composed
`{source_id}_{destination_id}_edge` under the edge type, and
`kgframes_endpoint._create_parent_edge` was likewise deterministic. This makes it
one function so the next edge to be minted inherits it.

COLLISION PROPERTY. The key is the pair of LOCAL ids, so two different pairs
collide only if both local ids repeat — and a collision would merge two
attachments into one edge, which is why the local part is taken from the whole
final segment rather than truncated. A URI with no usable final segment falls
back to a hash of the full URI rather than to an empty string, since
`"" + "_" + ""` would collide with every other unusable pair.

NOT A REPAIR. Edges already written with a random URI keep it. A frame written
repeatedly before this change still carries one stale edge per write, and
counting `Edge_hasEntityKGFrame` per (entity, frame) pair is how to find them.
"""
from __future__ import annotations

import hashlib

EDGE_URI_BASE = "http://vital.ai/haley.ai/app"

__all__ = ["EDGE_URI_BASE", "edge_local_id", "edge_uri"]


def edge_local_id(uri: str) -> str:
    """The final path segment of *uri*, or a stable digest when there is none.

    A trailing slash is dropped first, so `.../KGFrame/abc/` and
    `.../KGFrame/abc` are the same object and get the same id.
    """
    trimmed = str(uri).rstrip("/")
    local = trimmed.rsplit("/", 1)[-1] if "/" in trimmed else trimmed
    if local:
        return local
    # No segment to use. Hashing the ORIGINAL keeps distinct inputs distinct;
    # returning "" would make every such URI the same edge.
    return hashlib.sha256(str(uri).encode("utf-8")).hexdigest()[:16]


def edge_uri(edge_type: str, source_uri: str, destination_uri: str) -> str:
    """The URI for an edge of *edge_type* from *source_uri* to *destination_uri*.

    Deterministic, so writing the same edge twice writes the same URI and the
    second write is a no-op instead of a duplicate attachment.
    """
    return (f"{EDGE_URI_BASE}/{edge_type}/"
            f"{edge_local_id(source_uri)}_{edge_local_id(destination_uri)}_edge")
