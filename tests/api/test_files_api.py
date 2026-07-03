"""API tests: Files (FileNode) CRUD via VitalGraphClient.

Tests FileNode metadata lifecycle: create, list, get, update, delete.
Tests streaming upload/download using real test files.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_files_crud.py
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from vital_ai_domain.model.FileNode import FileNode

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_FILES_DIR = PROJECT_ROOT / "test_files"
PNG_FILE = TEST_FILES_DIR / "vampire_queen_baby.png"
PDF_FILE = TEST_FILES_DIR / "2502.16143v1.pdf"

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/files/"


def _make_file_node(name: str) -> FileNode:
    """Create a FileNode with a unique URI."""
    f = FileNode()
    f.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    f.name = name
    return f


class TestFilesCrud:
    """FileNode metadata lifecycle: create → list → get → update → delete."""

    async def test_create_file_nodes(self, vg_client, test_space, test_graph):
        """Create 3 FileNodes."""
        files = [
            _make_file_node("Annual Report"),
            _make_file_node("Company Logo"),
            _make_file_node("Data Export CSV"),
        ]
        cr = await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=files
        )
        assert cr.is_success, f"create failed: {cr.error_message}"
        assert cr.created_count == 3

    async def test_list_file_nodes(self, vg_client, test_space, test_graph):
        """List returns at least 3 FileNodes."""
        lr = await vg_client.files.list_files(
            space_id=test_space, graph_id=test_graph, page_size=50
        )
        assert lr.is_success
        assert lr.count >= 3

    async def test_get_file_node_by_uri(self, vg_client, test_space, test_graph):
        """Create then get a FileNode by URI."""
        f = _make_file_node("Gettable File")
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        gr = await vg_client.files.get_file(
            space_id=test_space, graph_id=test_graph, uri=str(f.URI)
        )
        assert gr.is_success
        assert gr.file is not None
        assert str(gr.file.name) == "Gettable File"

    async def test_update_file_node(self, vg_client, test_space, test_graph):
        """Create, update name, verify persisted."""
        f = _make_file_node("Before Update")
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        f.name = "After Update"
        ur = await vg_client.files.update_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )
        assert ur.is_success, f"update failed: {ur.error_message}"

        gr = await vg_client.files.get_file(
            space_id=test_space, graph_id=test_graph, uri=str(f.URI)
        )
        assert gr.is_success
        assert str(gr.file.name) == "After Update"

    async def test_delete_file_node(self, vg_client, test_space, test_graph):
        """Create then delete a FileNode, verify gone."""
        f = _make_file_node("DeleteMe File")
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        dr = await vg_client.files.delete_file(
            space_id=test_space, graph_id=test_graph, uri=str(f.URI)
        )
        assert dr.is_success

        gr = await vg_client.files.get_file(
            space_id=test_space, graph_id=test_graph, uri=str(f.URI)
        )
        assert not gr.is_success or gr.file is None


class TestFilesUploadDownload:
    """Upload/download using real test files via the authenticated client."""

    async def test_upload_png(self, vg_client, test_space, test_graph):
        """Upload PNG via client, verify success and reported size."""
        assert PNG_FILE.exists(), f"Test file missing: {PNG_FILE}"
        png_size = PNG_FILE.stat().st_size

        file_uri = f"{NS}upload_png_{uuid.uuid4().hex[:8]}"
        f = _make_file_node("Upload PNG")
        f.URI = file_uri
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        resp = await vg_client.files.upload_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri,
            source=str(PNG_FILE),
            content_type="image/png",
        )
        assert resp.is_success, f"upload failed: {resp.error_message}"
        assert resp.size == png_size

    async def test_upload_and_download_png(self, vg_client, test_space, test_graph):
        """Upload PNG then download as bytes, verify exact size."""
        assert PNG_FILE.exists()
        png_size = PNG_FILE.stat().st_size

        file_uri = f"{NS}updown_png_{uuid.uuid4().hex[:8]}"
        f = _make_file_node("Upload Download PNG")
        f.URI = file_uri
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        await vg_client.files.upload_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri,
            source=str(PNG_FILE),
            content_type="image/png",
        )

        content = await vg_client.files.download_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri, destination=None,
        )
        assert isinstance(content, bytes)
        assert len(content) == png_size

    async def test_upload_and_download_pdf(self, vg_client, test_space, test_graph):
        """Upload PDF then download as bytes, verify exact size."""
        assert PDF_FILE.exists()
        pdf_size = PDF_FILE.stat().st_size

        file_uri = f"{NS}updown_pdf_{uuid.uuid4().hex[:8]}"
        f = _make_file_node("Upload Download PDF")
        f.URI = file_uri
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        await vg_client.files.upload_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri,
            source=str(PDF_FILE),
            content_type="application/pdf",
        )

        content = await vg_client.files.download_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri, destination=None,
        )
        assert isinstance(content, bytes)
        assert len(content) == pdf_size

    async def test_download_to_file(self, vg_client, test_space, test_graph, tmp_path):
        """Upload PNG then download to a temp file, verify size matches."""
        assert PNG_FILE.exists()
        png_size = PNG_FILE.stat().st_size

        file_uri = f"{NS}dlfile_png_{uuid.uuid4().hex[:8]}"
        f = _make_file_node("Download to File PNG")
        f.URI = file_uri
        await vg_client.files.create_file(
            space_id=test_space, graph_id=test_graph, objects=[f]
        )

        await vg_client.files.upload_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri,
            source=str(PNG_FILE),
            content_type="image/png",
        )

        dest = tmp_path / "downloaded.png"
        await vg_client.files.download_file_content(
            space_id=test_space, graph_id=test_graph,
            file_uri=file_uri, destination=str(dest),
        )
        assert dest.exists()
        assert dest.stat().st_size == png_size
