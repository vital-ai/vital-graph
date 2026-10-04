"""The client's entity batch delete takes a list OR a comma-separated string.

`VitalGraphClient.delete_kgentities_batch` passes a comma-separated string to an
endpoint method that iterated it as a list, so "http://x/a,http://x/b" went out
as "h,t,t,p,:,/,/,x,/,a,,,h,...". The server matched no entity and answered
NO_OP — a success — while deleting nothing. And the wrappers on
`VitalGraphClient` could not pass `delete_entity_graph`, `recursive` or
`if_unmodified_since` at all (`issues/256`).
"""

import asyncio
from types import SimpleNamespace

import pytest

from vitalgraph.client.endpoint.kgentities_endpoint import KGEntitiesEndpoint


class _Resp:
    status_code = 200

    def json(self):
        return {"status": "deleted", "deleted_count": 2,
                "deleted_uris": ["http://x/a", "http://x/b"], "message": "ok"}


def _endpoint():
    ep = KGEntitiesEndpoint.__new__(KGEntitiesEndpoint)
    ep.sent = []
    ep._check_connection = lambda: None
    ep._get_server_url = lambda: "http://server"

    async def _make_request(method, url, params=None, **kw):
        ep.sent.append(params)
        return _Resp()
    ep._make_request = _make_request
    return ep


@pytest.mark.parametrize("uris", [
    "http://x/a,http://x/b", " http://x/a , http://x/b ", ["http://x/a", "http://x/b"]],
    ids=["string", "string-with-spaces", "list"])
def test_the_uris_go_out_whole(uris):
    ep = _endpoint()
    asyncio.run(ep.delete_kgentities_batch("sp", "g", uris))
    assert ep.sent[0]["uri_list"] == "http://x/a,http://x/b"


def test_the_wrappers_pass_the_new_arguments_through():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    calls = []

    async def _rec(*a, **k):
        calls.append(k)

    c = VitalGraphClient.__new__(VitalGraphClient)
    c.kgentities = SimpleNamespace(delete_kgentity=_rec, delete_kgentities_batch=_rec)
    c.kgframes = SimpleNamespace(delete_kgframe=_rec, delete_kgframes_batch=_rec,
                                 delete_kgframes_with_slots=_rec)
    asyncio.run(c.delete_kgentity("sp", "g", "u", delete_entity_graph=True,
                                  if_unmodified_since="t"))
    asyncio.run(c.delete_kgentities_batch("sp", "g", "a,b", delete_entity_graph=True))
    asyncio.run(c.delete_kgframe("sp", "g", "f", recursive=True, if_unmodified_since="t"))
    asyncio.run(c.delete_kgframes_batch("sp", "g", "f1,f2", recursive=True))
    asyncio.run(c.delete_kgframes_with_slots("sp", "g", "f1", recursive=True))
    assert calls[0] == {"delete_entity_graph": True, "if_unmodified_since": "t"}
    assert calls[1]["delete_entity_graph"] is True
    assert calls[2] == {"recursive": True, "if_unmodified_since": "t"}
    assert calls[3]["recursive"] is True and calls[4]["recursive"] is True
