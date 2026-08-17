"""A streamed upload must still report how many bytes it stored.

`put_object(length=-1)` is what makes the upload a stream — MinIO reads the
body in parts and never learns the total — so the size has to be observed on
the way past. The endpoint used to answer `file_size=0` with the comment "Size
unknown in streaming mode"; that was tolerable while the buffering
`POST /files/upload` still existed beside it, and became the only answer the
API gives once that endpoint was removed.

The counting is only correct if MinIO reads the body EXCLUSIVELY through
`data.read()`, so these tests drive the REAL `Minio.put_object` over a fake
transport rather than a hand-rolled stand-in of its loop. A stub that mimicked
the loop would pass while pinning our belief about MinIO instead of MinIO.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from minio import Minio
from minio.helpers import ObjectWriteResult

from vitalgraph.endpoint.files_streaming_impl import stream_upload_to_s3


class _FakeTransport:
    """A `Minio` with the four network calls of `put_object` cut out.

    Everything above them — the part loop, the one-byte lookahead, multipart
    promotion — is the library's own code running unmodified.
    """

    def __init__(self):
        self.client = Minio("localhost:9000", access_key="a", secret_key="b",
                            secure=False)
        self.stored = b""
        self.parts = []
        self.client._put_object = self._put_object
        self.client._create_multipart_upload = lambda *a, **k: "upload-1"
        self.client._upload_part = self._upload_part
        self.client._complete_multipart_upload = self._complete

    def _put_object(self, bucket, obj, data, headers, **kwargs):
        self.stored = data
        return ObjectWriteResult(bucket, obj, None, "etag-single", {})

    def _upload_part(self, bucket, obj, data, headers, upload_id, part_number):
        self.parts.append(data)
        self.stored += data
        return f"etag-{part_number}"

    def _complete(self, bucket, obj, upload_id, parts, sse=None):
        return ObjectWriteResult(bucket, obj, None, "etag-multi", {})


class _FakeFileManager:
    def __init__(self):
        self.transport = _FakeTransport()
        self.client = self.transport.client
        self.bucket_name = "files"


class _UploadFile:
    """Only `.file` is touched by `stream_upload_to_s3`."""

    def __init__(self, content: bytes):
        self.file = io.BytesIO(content)


MIN_PART_SIZE = 5 * 1024 * 1024      # MinIO's floor; smaller raises ValueError


def _upload(content: bytes, part_size: int | None = None):
    fm = _FakeFileManager()
    if part_size is not None:
        # The endpoint asks for 10 MiB parts. Shrinking that to MinIO's floor
        # halves the body a multipart test has to build.
        real_put = fm.client.put_object
        fm.client.put_object = lambda *a, **k: real_put(
            *a, **{**k, "part_size": part_size})
    result = asyncio.run(stream_upload_to_s3(file=_UploadFile(content),
                                             file_manager=fm,
                                             object_key="obj"))
    return result, fm.transport


@pytest.mark.parametrize("size", [0, 1, 57, 8192, 8193, 100_000])
def test_reported_size_matches_the_bytes_stored(size):
    """The number in the response is the number of bytes that reached storage.

    Not the Content-Length header and not what the client claimed to send —
    both can lie, and neither is available here anyway.
    """
    content = bytes(range(256)) * (size // 256) + b"x" * (size % 256)
    assert len(content) == size

    result, transport = _upload(content)

    assert result["size"] == size
    assert transport.stored == content, "the fake transport saw different bytes"


def test_size_is_exact_across_the_multipart_lookahead():
    """The second read pattern. Every case above uses the first.

    Under 5 MiB `put_object` drains the stream and hands it to `_put_object` in
    one go. Past that it loops: reads of `part_size + 1`, the spare byte
    carried forward as a PREFIX to the next read rather than re-read, and
    however many short reads the stream feels like returning underneath. The
    counter has to be right under both, and a body that never reaches a second
    part cannot say anything about the second.

    The body has to clear 5 MiB to get there — MinIO rejects a smaller part
    size — so there is no cheaper way to buy this.
    """
    content = (b"abcdefgh" * (MIN_PART_SIZE // 8)) + b"tail" * 1024

    result, transport = _upload(content, part_size=MIN_PART_SIZE)

    assert len(transport.parts) > 1, "did not exercise the multipart path"
    assert result["size"] == len(content)
    assert transport.stored == content


def test_the_endpoint_passes_the_size_through():
    """The count is only worth having if it survives the last hop.

    `FileUploadResponse.file_size` is what an API consumer actually reads, and
    the endpoint spent the life of this route hardcoding it to 0.
    """
    from vitalgraph.endpoint.files_endpoint import FilesEndpoint

    endpoint = FilesEndpoint(space_manager=None, auth_dependency=lambda: {})
    fm = _FakeFileManager()
    fm.get_file_url = lambda key: f"s3://files/{key}"
    endpoint.file_manager = fm

    class _Node:
        fileURL = None
        fileType = None

    class _FilesImpl:
        async def get_file_by_uri(self, **kwargs):
            return _Node()

        async def update_files(self, **kwargs):
            return None

    endpoint.files_impl = _FilesImpl()

    upload = _UploadFile(b"z" * 4097)
    upload.content_type = "application/octet-stream"
    upload.filename = "z.bin"

    response = asyncio.run(endpoint._upload_file_stream(
        space_id="s", graph_id="g", uri="urn:f/1", file=upload,
        chunk_size=8192, current_user={"username": "u"}))

    assert response.file_size == 4097


def test_size_is_absent_from_a_failed_upload():
    """A raise must not leave a plausible-looking size behind."""
    fm = _FakeFileManager()
    fm.client.put_object = lambda *a, **k: (_ for _ in ()).throw(
        OSError("bucket unreachable"))

    with pytest.raises(OSError):
        asyncio.run(stream_upload_to_s3(file=_UploadFile(b"abc"),
                                        file_manager=fm, object_key="obj"))
