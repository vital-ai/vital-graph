"""
Files CRUD Test Case — SPARQL-SQL Backend

Tests FileNode metadata lifecycle: create, list, get, update, delete.
Tests regular and streaming upload/download using real files from test_files/.
"""

import logging
import time
from pathlib import Path
from typing import Dict, Any

from vital_ai_domain.model.FileNode import FileNode

logger = logging.getLogger(__name__)

NS = "http://example.org/sqlfile/"

# Real test files (same as other file test scripts)
PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_FILES_DIR = PROJECT_ROOT / "test_files"
DOWNLOAD_DIR = PROJECT_ROOT / "test_files_download"

PDF_FILE = TEST_FILES_DIR / "2502.16143v1.pdf"
PNG_FILE = TEST_FILES_DIR / "vampire_queen_baby.png"


def _make_file_node(uri: str, name: str) -> FileNode:
    """Create a FileNode with the given URI and name."""
    f = FileNode()
    f.URI = uri
    f.name = name
    return f


class FilesCrudTester:
    """Client-based test for Files CRUD + upload/download against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _pass(self, results, label):
        logger.info(f"✅ PASS: {label}")
        results["tests_passed"] += 1

    def _fail(self, results, label, err):
        logger.error(f"❌ FAIL: {label} — {err}")
        results["errors"].append(f"{label}: {err}")
        results["tests_failed"] += 1

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "Files CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Files CRUD + Upload/Download")
        logger.info(f"{'=' * 80}")

        # Verify test files exist
        if not PDF_FILE.exists():
            logger.error(f"❌ Test file not found: {PDF_FILE}")
            results["errors"].append(f"Test file missing: {PDF_FILE}")
            return results
        if not PNG_FILE.exists():
            logger.error(f"❌ Test file not found: {PNG_FILE}")
            results["errors"].append(f"Test file missing: {PNG_FILE}")
            return results
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        f1 = _make_file_node(f"{NS}doc_report", "Annual Report")
        f2 = _make_file_node(f"{NS}img_logo", "Company Logo")
        f3 = _make_file_node(f"{NS}data_export", "Data Export CSV")

        # --- 1. Create FileNodes ---
        results["tests_run"] += 1
        try:
            cr = await self.client.files.create_file(
                space_id=space_id, graph_id=graph_id,
                objects=[f1, f2, f3])
            if cr.is_success and cr.created_count == 3:
                self._pass(results, "Create 3 FileNodes")
            else:
                raise Exception(
                    f"created_count={getattr(cr, 'created_count', '?')}, "
                    f"msg={getattr(cr, 'error_message', cr)}")
        except Exception as e:
            self._fail(results, "Create FileNodes", e)
            return results  # can't continue

        # --- 2. List FileNodes ---
        results["tests_run"] += 1
        try:
            lr = await self.client.files.list_files(
                space_id=space_id, graph_id=graph_id, page_size=50)
            if lr.is_success and lr.count >= 3:
                self._pass(results, f"List FileNodes — count={lr.count}")
            else:
                raise Exception(
                    f"count={getattr(lr, 'count', '?')}, "
                    f"msg={getattr(lr, 'error_message', lr)}")
        except Exception as e:
            self._fail(results, "List FileNodes", e)

        # --- 3. Get FileNode by URI ---
        results["tests_run"] += 1
        try:
            gr = await self.client.files.get_file(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}doc_report")
            if gr.is_success and gr.file is not None:
                got_name = str(gr.file.name) if hasattr(gr.file, 'name') else None
                self._pass(results, f"Get FileNode — name={got_name}")
            else:
                raise Exception(f"msg={getattr(gr, 'error_message', gr)}")
        except Exception as e:
            self._fail(results, "Get FileNode", e)

        # --- 4. Update FileNode ---
        results["tests_run"] += 1
        try:
            f1_updated = _make_file_node(f"{NS}doc_report", "Annual Report 2025")
            ur = await self.client.files.update_file(
                space_id=space_id, graph_id=graph_id,
                objects=[f1_updated])
            if ur.is_success:
                self._pass(results, "Update FileNode")
            else:
                raise Exception(f"msg={getattr(ur, 'error_message', ur)}")
        except Exception as e:
            self._fail(results, "Update FileNode", e)

        # --- 5. Verify update ---
        results["tests_run"] += 1
        try:
            gr2 = await self.client.files.get_file(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}doc_report")
            if gr2.is_success and gr2.file is not None:
                got_name = str(gr2.file.name) if hasattr(gr2.file, 'name') else None
                if got_name == "Annual Report 2025":
                    self._pass(results, f"Verify update — name={got_name}")
                else:
                    raise Exception(f"expected 'Annual Report 2025', got '{got_name}'")
            else:
                raise Exception(f"msg={getattr(gr2, 'error_message', gr2)}")
        except Exception as e:
            self._fail(results, "Verify update", e)

        # --- 6. Streaming upload (real PNG via AsyncFilePathGenerator) ---
        results["tests_run"] += 1
        try:
            from vitalgraph.client.binary.async_streaming import AsyncFilePathGenerator
            png_size = PNG_FILE.stat().st_size
            generator = AsyncFilePathGenerator(
                file_path=str(PNG_FILE),
                chunk_size=8192,
                content_type="image/png"
            )
            t0 = time.perf_counter()
            sup = await self.client.files.upload_file_stream_async(
                space_id=space_id, graph_id=graph_id,
                file_uri=f"{NS}doc_report",
                source=generator,
                chunk_size=8192)
            elapsed = time.perf_counter() - t0
            if sup.is_success:
                mb = png_size / (1024 * 1024)
                self._pass(results,
                           f"Streaming upload PNG ({mb:.1f} MB) — {elapsed:.2f}s")
            else:
                raise Exception(f"msg={getattr(sup, 'error_message', sup)}")
        except Exception as e:
            self._fail(results, "Streaming upload (PNG)", e)

        # --- 7. Streaming download to bytes ---
        results["tests_run"] += 1
        try:
            t0 = time.perf_counter()
            content = await self.client.files.download_file_content(
                space_id=space_id, graph_id=graph_id,
                file_uri=f"{NS}doc_report",
                destination=None)
            elapsed = time.perf_counter() - t0
            if isinstance(content, bytes) and len(content) > 0:
                self._pass(results,
                           f"Streaming download — {len(content)} bytes, {elapsed:.2f}s")
            else:
                raise Exception(f"expected bytes, got {type(content)}")
        except Exception as e:
            self._fail(results, "Streaming download", e)

        # --- 8. Streaming download to file ---
        results["tests_run"] += 1
        download_path = DOWNLOAD_DIR / "sql_stream_download.png"
        try:
            t0 = time.perf_counter()
            await self.client.files.download_file_content(
                space_id=space_id, graph_id=graph_id,
                file_uri=f"{NS}doc_report",
                destination=str(download_path))
            elapsed = time.perf_counter() - t0
            if download_path.exists() and download_path.stat().st_size > 0:
                dl_size = download_path.stat().st_size
                self._pass(results,
                           f"Streaming download to file — {dl_size} bytes, {elapsed:.2f}s")
            else:
                raise Exception("downloaded file is empty or missing")
        except Exception as e:
            self._fail(results, "Streaming download to file", e)
        finally:
            download_path.unlink(missing_ok=True)

        # --- 9. Delete single FileNode ---
        results["tests_run"] += 1
        try:
            dr = await self.client.files.delete_file(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}img_logo")
            if dr.is_success:
                self._pass(results, "Delete FileNode (img_logo)")
            else:
                raise Exception(f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            self._fail(results, "Delete FileNode", e)

        # --- 10. Verify img_logo deleted ---
        results["tests_run"] += 1
        try:
            gr3 = await self.client.files.get_file(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}img_logo")
            if not gr3.is_success or gr3.file is None:
                self._pass(results, "Verify img_logo deleted")
            else:
                raise Exception("img_logo still exists after delete")
        except Exception as e:
            self._fail(results, "Verify img_logo deleted", e)

        # --- 11. List remaining ---
        results["tests_run"] += 1
        try:
            lr2 = await self.client.files.list_files(
                space_id=space_id, graph_id=graph_id, page_size=50)
            remaining = lr2.count if lr2.is_success else -1
            if remaining == 2:
                self._pass(results, f"Remaining FileNodes — {remaining}")
            else:
                raise Exception(f"expected 2, got {remaining}")
        except Exception as e:
            self._fail(results, "Remaining FileNodes", e)

        # --- 12. Batch delete ---
        results["tests_run"] += 1
        try:
            dr2 = await self.client.files.delete_files_batch(
                space_id=space_id, graph_id=graph_id,
                uri_list=f"{NS}doc_report,{NS}data_export")
            if isinstance(dr2, dict):
                deleted = dr2.get('deleted_count', 0)
                if deleted >= 2:
                    self._pass(results, f"Batch delete — deleted_count={deleted}")
                else:
                    raise Exception(f"deleted_count={deleted}")
            elif hasattr(dr2, 'is_success') and dr2.is_success:
                self._pass(results, "Batch delete")
            else:
                raise Exception(f"unexpected response: {dr2}")
        except Exception as e:
            self._fail(results, "Batch delete", e)

        # --- 13. Final verification ---
        results["tests_run"] += 1
        try:
            lr3 = await self.client.files.list_files(
                space_id=space_id, graph_id=graph_id, page_size=50)
            remaining = lr3.count if lr3.is_success else -1
            if remaining == 0:
                self._pass(results, "Final verification — 0 FileNodes remaining")
            else:
                raise Exception(f"expected 0, got {remaining}")
        except Exception as e:
            self._fail(results, "Final verification", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results
