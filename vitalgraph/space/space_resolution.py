"""Make sure a request's space is known to this process before it runs.

`issues/348`. Several server instances share one database. Each process keeps
its own map of space id -> storage key (`space_names`), and `space_prefix`
names every per-space table from that map ALONE: it is synchronous, so it
cannot read the database, and for a space missing from the map it falls back
to the bare id. A space created on instance A is learnt by instance B from a
NOTIFY, but B handles it asynchronously; in production a request reached B
~180 ms before B had loaded the key and failed with "relation does not exist"
on `<space_id>_vector_index`.

This dependency closes that window for every route with a `space_id` query or
path parameter: before the handler runs, a space this process cannot name is
re-read from its row (`SpaceManager.ensure_space_loaded`, which loads the key).
A known space costs a dict lookup; an unknown one, one indexed read; an id
that does not exist stays unknown and the handler reports it as before.

It depends on the auth dependency itself, so it runs only for authenticated
requests (a made-up id from an anonymous caller costs nothing), and FastAPI's
per-request dependency cache keeps auth to a single run.

Routes that name their space in the BODY are not covered here and resolve it
themselves: import/export jobs (`ImportExportJobManager._run_job`), process
triggers, and the kgentities counts route (`get_space_or_load`).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from fastapi import Depends, Request

logger = logging.getLogger(__name__)


def space_resolving_dependency(get_space_manager: Callable[[], Optional[Any]],
                               auth_dependency: Callable) -> Callable:
    """The dependency to mount on every router with space-scoped routes."""

    async def resolve_request_space(
        request: Request,
        current_user: Dict = Depends(auth_dependency),
    ) -> None:
        space_id = (request.query_params.get("space_id")
                    or request.path_params.get("space_id"))
        if not space_id:
            return
        space_manager = get_space_manager()
        if space_manager is None:
            return
        try:
            await space_manager.ensure_space_loaded(space_id)
        except Exception as e:
            # Never fail the request here: the handler then behaves exactly as
            # it did before this dependency existed.
            logger.warning("resolve_request_space(%s) failed: %s", space_id, e)

    return resolve_request_space
