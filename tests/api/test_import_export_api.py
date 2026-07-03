"""API tests: Import/Export job lifecycle via VitalGraphClient.

Tests the import and export job management endpoints:
  - Create job → list → get → delete (both import and export)
  - Status polling for created jobs
  - Upload file → execute → poll until done → verify data (import)
  - Execute → poll until done → download file → verify content (export)
  - Error cases: 404, 409 conflicts
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from vitalgraph.model.import_model import ImportJobCreate, ImportMode, JobStatus
from vitalgraph.model.export_model import ExportJobCreate, FileFormat

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

# Small N-Triples fixture for import testing
# NOTE: The import engine parses as application/n-triples (3-component lines).
# The target graph is specified on the job, not in the file.
SAMPLE_NTRIPLES = """\
<urn:test:s1> <urn:test:p1> "hello" .
<urn:test:s1> <urn:test:p2> "world" .
<urn:test:s2> <urn:test:p1> "foo" .
"""


# ---------------------------------------------------------------------------
# Import job lifecycle
# ---------------------------------------------------------------------------

class TestImportJobLifecycle:
    """Import job CRUD lifecycle."""

    async def test_create_import_job(self, vg_client, test_space, test_graph):
        """Create an import job and verify response."""
        req = ImportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            mode=ImportMode.APPEND,
        )
        resp = await vg_client.imports.create_import_job(req)
        assert resp.job_id
        assert resp.job.space_id == test_space
        assert resp.job.status == JobStatus.CREATED

    async def test_list_import_jobs(self, vg_client, test_space, test_graph):
        """List import jobs — should find at least one for our space."""
        req = ImportJobCreate(space_id=test_space, graph_uri=test_graph)
        create_resp = await vg_client.imports.create_import_job(req)

        list_resp = await vg_client.imports.list_import_jobs(space_id=test_space)
        assert list_resp.jobs is not None
        job_ids = [j.job_id for j in list_resp.jobs]
        assert create_resp.job_id in job_ids

    async def test_get_import_job(self, vg_client, test_space, test_graph):
        """Get a specific import job by ID."""
        req = ImportJobCreate(space_id=test_space, graph_uri=test_graph)
        create_resp = await vg_client.imports.create_import_job(req)

        get_resp = await vg_client.imports.get_import_job(create_resp.job_id)
        assert get_resp.job.job_id == create_resp.job_id
        assert get_resp.job.space_id == test_space

    async def test_get_import_status(self, vg_client, test_space, test_graph):
        """Poll status for a newly created job — should be 'created'."""
        req = ImportJobCreate(space_id=test_space, graph_uri=test_graph)
        create_resp = await vg_client.imports.create_import_job(req)

        status_resp = await vg_client.imports.get_import_status(create_resp.job_id)
        assert status_resp.job_id == create_resp.job_id
        assert status_resp.status == JobStatus.CREATED
        assert status_resp.progress_pct == 0.0

    async def test_get_import_log_empty(self, vg_client, test_space, test_graph):
        """Log entries for a new job should be empty."""
        req = ImportJobCreate(space_id=test_space, graph_uri=test_graph)
        create_resp = await vg_client.imports.create_import_job(req)

        log_resp = await vg_client.imports.get_import_log(create_resp.job_id)
        assert log_resp.job_id == create_resp.job_id
        assert log_resp.total_entries == 0

    async def test_delete_import_job(self, vg_client, test_space, test_graph):
        """Delete an import job and verify it's gone."""
        req = ImportJobCreate(space_id=test_space, graph_uri=test_graph)
        create_resp = await vg_client.imports.create_import_job(req)

        del_resp = await vg_client.imports.delete_import_job(create_resp.job_id)
        assert del_resp.job_id == create_resp.job_id

        # Verify the job no longer appears in list
        list_resp = await vg_client.imports.list_import_jobs(space_id=test_space)
        job_ids = [j.job_id for j in list_resp.jobs]
        assert create_resp.job_id not in job_ids


# ---------------------------------------------------------------------------
# Export job lifecycle
# ---------------------------------------------------------------------------

class TestExportJobLifecycle:
    """Export job CRUD lifecycle."""

    async def test_create_export_job(self, vg_client, test_space, test_graph):
        """Create an export job and verify response."""
        req = ExportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            file_format=FileFormat.NQ,
        )
        resp = await vg_client.exports.create_export_job(req)
        assert resp.job_id
        assert resp.job.space_id == test_space
        assert resp.job.status == JobStatus.CREATED

    async def test_list_export_jobs(self, vg_client, test_space, test_graph):
        """List export jobs — should find at least one for our space."""
        req = ExportJobCreate(space_id=test_space, file_format=FileFormat.NQ)
        create_resp = await vg_client.exports.create_export_job(req)

        list_resp = await vg_client.exports.list_export_jobs(space_id=test_space)
        assert list_resp.jobs is not None
        job_ids = [j.job_id for j in list_resp.jobs]
        assert create_resp.job_id in job_ids

    async def test_get_export_job(self, vg_client, test_space, test_graph):
        """Get a specific export job by ID."""
        req = ExportJobCreate(space_id=test_space, file_format=FileFormat.NQ)
        create_resp = await vg_client.exports.create_export_job(req)

        get_resp = await vg_client.exports.get_export_job(create_resp.job_id)
        assert get_resp.job.job_id == create_resp.job_id
        assert get_resp.job.space_id == test_space

    async def test_get_export_status(self, vg_client, test_space, test_graph):
        """Poll status for a newly created export job — should be 'created'."""
        req = ExportJobCreate(space_id=test_space, file_format=FileFormat.NQ)
        create_resp = await vg_client.exports.create_export_job(req)

        status_resp = await vg_client.exports.get_export_status(create_resp.job_id)
        assert status_resp.job_id == create_resp.job_id
        assert status_resp.status == JobStatus.CREATED
        assert status_resp.progress_pct == 0.0

    async def test_delete_export_job(self, vg_client, test_space, test_graph):
        """Delete an export job and verify it's gone."""
        req = ExportJobCreate(space_id=test_space, file_format=FileFormat.NQ)
        create_resp = await vg_client.exports.create_export_job(req)

        del_resp = await vg_client.exports.delete_export_job(create_resp.job_id)
        assert del_resp.job_id == create_resp.job_id

        # Verify removed
        list_resp = await vg_client.exports.list_export_jobs(space_id=test_space)
        job_ids = [j.job_id for j in list_resp.jobs]
        assert create_resp.job_id not in job_ids


# ---------------------------------------------------------------------------
# Import: upload + execute + poll
# ---------------------------------------------------------------------------

class TestImportExecution:
    """Import job full workflow: upload file → execute → poll → verify."""

    @pytest.fixture()
    async def ntriples_file(self, tmp_path):
        """Write sample N-Triples to a temp file."""
        p = tmp_path / "test_import.nt"
        p.write_text(SAMPLE_NTRIPLES, encoding="utf-8")
        return str(p)

    async def test_upload_file(self, vg_client, test_space, test_graph, ntriples_file):
        """Upload a file to an import job and verify response."""
        req = ImportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            mode=ImportMode.APPEND,
        )
        create_resp = await vg_client.imports.create_import_job(req)

        upload_resp = await vg_client.imports.upload_import_file(
            create_resp.job_id, ntriples_file,
        )
        assert upload_resp.job_id == create_resp.job_id
        assert upload_resp.filename == "test_import.nt"
        assert upload_resp.file_size > 0

        # Cleanup
        await vg_client.imports.delete_import_job(create_resp.job_id)

    async def test_execute_import_and_poll(self, vg_client, test_space, test_graph, ntriples_file):
        """Upload → execute → poll until completed or timeout."""
        req = ImportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            mode=ImportMode.APPEND,
        )
        create_resp = await vg_client.imports.create_import_job(req)
        await vg_client.imports.upload_import_file(create_resp.job_id, ntriples_file)

        exec_resp = await vg_client.imports.execute_import_job(create_resp.job_id)
        assert exec_resp.execution_started is True

        # Poll for completion (max 30s)
        terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        final_status = None
        for _ in range(30):
            status_resp = await vg_client.imports.get_import_status(create_resp.job_id)
            if status_resp.status in terminal_statuses:
                final_status = status_resp.status
                break
            await asyncio.sleep(1)

        if final_status != JobStatus.COMPLETED:
            # Fetch log for diagnosis
            log_resp = await vg_client.imports.get_import_log(create_resp.job_id)
            job_resp = await vg_client.imports.get_import_job(create_resp.job_id)
            error_msg = getattr(job_resp.job, 'error_message', None)
            log_entries = log_resp.log_entries if log_resp.log_entries else []
            diag = f"status={final_status}, error={error_msg}, log={log_entries}"
            # Cleanup before assertion
            await vg_client.imports.delete_import_job(create_resp.job_id)
            pytest.fail(f"Import did not complete: {diag}")

        # Cleanup
        await vg_client.imports.delete_import_job(create_resp.job_id)

    async def test_execute_without_upload_fails(self, vg_client, test_space, test_graph):
        """Executing a job with no uploaded file should return 400."""
        req = ImportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            mode=ImportMode.APPEND,
        )
        create_resp = await vg_client.imports.create_import_job(req)

        with pytest.raises(Exception) as exc_info:
            await vg_client.imports.execute_import_job(create_resp.job_id)
        # Should be a 400 error (no file uploaded)
        assert "400" in str(exc_info.value) or "No file" in str(exc_info.value)

        # Cleanup
        await vg_client.imports.delete_import_job(create_resp.job_id)


# ---------------------------------------------------------------------------
# Export: execute + poll + download
# ---------------------------------------------------------------------------

class TestExportExecution:
    """Export job full workflow: execute → poll → download → verify."""

    async def _insert_sample_data(self, vg_client, space_id, graph_id):
        """Insert some triples so export has data to export."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest

        sparql = (
            f'INSERT DATA {{ GRAPH <{graph_id}> {{ '
            f'<urn:test:s1> <urn:test:p1> "hello" . '
            f'<urn:test:s1> <urn:test:p2> "world" . '
            f'<urn:test:s2> <urn:test:p1> "foo" . '
            f'}} }}'
        )
        result = await vg_client.sparql.execute_sparql_insert(
            space_id, SPARQLInsertRequest(update=sparql),
        )
        assert result.success, f"Sample data insert failed: {result.error}"

    async def test_execute_export_and_poll(self, vg_client, test_space, test_graph):
        """Create export → execute → poll until completed."""
        await self._insert_sample_data(vg_client, test_space, test_graph)

        req = ExportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            file_format=FileFormat.NQ,
        )
        create_resp = await vg_client.exports.create_export_job(req)

        exec_resp = await vg_client.exports.execute_export_job(create_resp.job_id)
        assert exec_resp.execution_started is True

        # Poll for completion (max 30s)
        terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        final_status = None
        for _ in range(30):
            status_resp = await vg_client.exports.get_export_status(create_resp.job_id)
            if status_resp.status in terminal_statuses:
                final_status = status_resp.status
                break
            await asyncio.sleep(1)

        assert final_status == JobStatus.COMPLETED, (
            f"Export did not complete: status={final_status}"
        )

        # Cleanup
        await vg_client.exports.delete_export_job(create_resp.job_id)

    async def test_download_export_file(self, vg_client, test_space, test_graph):
        """Execute export → poll → download file → verify non-empty."""
        await self._insert_sample_data(vg_client, test_space, test_graph)

        req = ExportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            file_format=FileFormat.NQ,
        )
        create_resp = await vg_client.exports.create_export_job(req)
        await vg_client.exports.execute_export_job(create_resp.job_id)

        # Poll for completion
        terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        for _ in range(30):
            status_resp = await vg_client.exports.get_export_status(create_resp.job_id)
            if status_resp.status in terminal_statuses:
                break
            await asyncio.sleep(1)

        assert status_resp.status == JobStatus.COMPLETED

        # Download
        with tempfile.NamedTemporaryFile(suffix=".nq", delete=False) as f:
            output_path = f.name
        try:
            ok = await vg_client.exports.download_export_file(
                create_resp.job_id, output_path,
            )
            assert ok is True
            content = open(output_path, "r").read()
            assert len(content) > 0
            # Verify our test data is present
            assert "urn:test:s1" in content
        finally:
            os.unlink(output_path)
            await vg_client.exports.delete_export_job(create_resp.job_id)

    async def test_download_before_complete_fails(self, vg_client, test_space, test_graph):
        """Downloading from a not-yet-completed job should fail (409)."""
        req = ExportJobCreate(
            space_id=test_space,
            graph_uri=test_graph,
            file_format=FileFormat.NQ,
        )
        create_resp = await vg_client.exports.create_export_job(req)

        # Do NOT execute — try to download immediately
        with pytest.raises(Exception) as exc_info:
            await vg_client.exports.download_export_file(
                create_resp.job_id, "/tmp/should_not_exist.nq",
            )
        assert "409" in str(exc_info.value) or "not completed" in str(exc_info.value)

        # Cleanup
        await vg_client.exports.delete_export_job(create_resp.job_id)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestImportExportErrors:
    """Error handling for import/export endpoints."""

    async def test_get_nonexistent_import_job(self, vg_client):
        """Getting a non-existent import job returns 404."""
        with pytest.raises(Exception) as exc_info:
            await vg_client.imports.get_import_job("00000000-0000-0000-0000-000000000000")
        assert "404" in str(exc_info.value)

    async def test_get_nonexistent_export_job(self, vg_client):
        """Getting a non-existent export job returns 404."""
        with pytest.raises(Exception) as exc_info:
            await vg_client.exports.get_export_job("00000000-0000-0000-0000-000000000000")
        assert "404" in str(exc_info.value)

    async def test_delete_nonexistent_import_job(self, vg_client):
        """Deleting a non-existent import job returns 404."""
        with pytest.raises(Exception) as exc_info:
            await vg_client.imports.delete_import_job("00000000-0000-0000-0000-000000000000")
        assert "404" in str(exc_info.value)

    async def test_delete_nonexistent_export_job(self, vg_client):
        """Deleting a non-existent export job returns 404."""
        with pytest.raises(Exception) as exc_info:
            await vg_client.exports.delete_export_job("00000000-0000-0000-0000-000000000000")
        assert "404" in str(exc_info.value)

    async def test_execute_nonexistent_import_job(self, vg_client):
        """Executing a non-existent import job returns 404."""
        with pytest.raises(Exception) as exc_info:
            await vg_client.imports.execute_import_job("00000000-0000-0000-0000-000000000000")
        assert "404" in str(exc_info.value)

    async def test_execute_nonexistent_export_job(self, vg_client):
        """Executing a non-existent export job returns 404."""
        with pytest.raises(Exception) as exc_info:
            await vg_client.exports.execute_export_job("00000000-0000-0000-0000-000000000000")
        assert "404" in str(exc_info.value)

    async def test_list_import_jobs_filter_by_status(self, vg_client, test_space, test_graph):
        """Filter import jobs by status should work."""
        req = ImportJobCreate(space_id=test_space, graph_uri=test_graph)
        create_resp = await vg_client.imports.create_import_job(req)

        # Filter by "created" status
        list_resp = await vg_client.imports.list_import_jobs(
            space_id=test_space, status="created",
        )
        job_ids = [j.job_id for j in list_resp.jobs]
        assert create_resp.job_id in job_ids

        # Filter by "completed" — our new job should NOT appear
        list_resp2 = await vg_client.imports.list_import_jobs(
            space_id=test_space, status="completed",
        )
        job_ids2 = [j.job_id for j in list_resp2.jobs]
        assert create_resp.job_id not in job_ids2

        # Cleanup
        await vg_client.imports.delete_import_job(create_resp.job_id)

    async def test_list_export_jobs_filter_by_status(self, vg_client, test_space, test_graph):
        """Filter export jobs by status should work."""
        req = ExportJobCreate(space_id=test_space, file_format=FileFormat.NQ)
        create_resp = await vg_client.exports.create_export_job(req)

        # Filter by "created"
        list_resp = await vg_client.exports.list_export_jobs(
            space_id=test_space, status="created",
        )
        job_ids = [j.job_id for j in list_resp.jobs]
        assert create_resp.job_id in job_ids

        # Cleanup
        await vg_client.exports.delete_export_job(create_resp.job_id)
