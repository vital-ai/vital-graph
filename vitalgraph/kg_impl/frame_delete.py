"""The frame delete both routes share (`issues/256`).

`DELETE /kgentities/kgframes` and `DELETE /kgframes` were two implementations
with different scopes, statuses and no lock. Both now call
`SparqlSQLBackendAdapter.delete_frame_subtrees` through here, so they also
answer the same way:

- DELETED   every requested frame that existed was deleted (some may have
            been absent; `absent_uris` names them);
- NO_OP     none of the requested frames existed;
- INVALID_REQUEST  refused, nothing deleted (`DeleteRefused`, or one
            `if_unmodified_since` for several frames);
- CONFLICT  the guard's stamp had moved, nothing deleted;
- STORE_FAILED  the guard could not be decided, or the delete failed.
"""

import logging
from typing import List, Optional, Tuple

from ..model.kgframes_model import FrameDeleteResponse
from ..model.result_status import OperationStatus
from .frame_grouping import UngroupableSlot
from .kg_backend_utils import (
    AmbiguousPrecondition, DeleteRefused, GuardUnsatisfiable, StaleWrite)
from .refusals import RequestRefused

logger = logging.getLogger(__name__)


async def delete_frames(backend_adapter, space_id: str, graph_id: str,
                        frame_uris: List[str], *, recursive: bool,
                        owner_entity_uri: Optional[str] = None,
                        if_unmodified_since: Optional[str] = None
                        ) -> Tuple[FrameDeleteResponse, List[str]]:
    """Delete frame subtrees and say what happened.

    Returns the response and the URI of every subject removed, for the caller's
    auto-sync (empty unless something was deleted). With `owner_entity_uri` the
    guard is the entity; without it, the one root frame named.
    """
    roots = list(dict.fromkeys(frame_uris))

    def _refused(status, message) -> Tuple[FrameDeleteResponse, List[str]]:
        return FrameDeleteResponse(status=status, message=message,
                                   deleted_count=0, deleted_uris=[]), []

    guard_subject = owner_entity_uri
    if owner_entity_uri is None and if_unmodified_since is not None:
        # A precondition names one version of ONE frame (`issues/253`).
        if len(roots) != 1:
            return _refused(OperationStatus.INVALID_REQUEST,
                            str(AmbiguousPrecondition(len(roots))))
        guard_subject = roots[0]

    try:
        result = await backend_adapter.delete_frame_subtrees(
            space_id, graph_id, roots, recursive=recursive,
            owner_entity_uri=owner_entity_uri,
            if_unmodified_since=if_unmodified_since,
            guard_subject=guard_subject)
    except RequestRefused as e:
        # `UngroupableSlot` cannot arise from a delete; listed so every refusal
        # path lets the whole family past (`test_a_refusal_reaches_the_caller`).
        return _refused(OperationStatus.INVALID_REQUEST, str(e))
    except StaleWrite as e:
        logger.warning("Frame delete refused as stale: %s", e)
        return _refused(OperationStatus.CONFLICT, str(e))
    except GuardUnsatisfiable as e:
        return _refused(OperationStatus.STORE_FAILED, str(e))
    except Exception as e:
        logger.error("Frame delete failed: %s", e)
        return _refused(OperationStatus.STORE_FAILED,
                        f"Frame delete failed, nothing was deleted: {e}")

    if not result.deleted_frames:
        return FrameDeleteResponse(
            status=OperationStatus.NO_OP,
            message=f"None of the {len(roots)} requested frame(s) exist - "
                    f"no deletion performed",
            deleted_count=0, deleted_uris=[],
            absent_uris=result.absent_frames), []

    message = (f"Successfully deleted {len(result.deleted_frames)} frame(s) "
               f"({len(result.member_uris)} subjects)")
    if result.absent_frames:
        message += f"; {len(result.absent_frames)} were already absent"
    return FrameDeleteResponse(
        status=OperationStatus.DELETED, message=message,
        deleted_count=len(result.deleted_frames),
        deleted_uris=result.deleted_frames,
        absent_uris=result.absent_frames), result.member_uris
