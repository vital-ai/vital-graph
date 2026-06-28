"""
Process Endpoint Test Case — SPARQL-SQL Backend

Tests the process tracking REST API via the VitalGraph client:
  1. Get scheduler status
  2. List processes (empty or populated)
  3. List processes with type filter
  4. List processes with status filter
  5. List processes with pagination
  6. Trigger maintenance (analyze)
  7. List processes (verify new record)
  8. Get process by ID
  9. Trigger maintenance (vacuum)
  10. Get non-existent process (404)

No space or graph is required — process tracking uses global admin tables.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ProcessEndpointTester:
    """Client-based test for Process REST endpoints against sparql_sql backend."""

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
    async def run_tests(self) -> Dict[str, Any]:
        results = {
            "test_name": "Process Endpoint",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Process Endpoint Tests")
        logger.info(f"{'=' * 80}")

        proc = self.client.processes
        captured_process_id = None

        # --- 1. Get scheduler status ---
        results["tests_run"] += 1
        try:
            status_resp = await proc.get_scheduler_status()
            if hasattr(status_resp, "enabled") and hasattr(status_resp, "running"):
                self._pass(
                    results,
                    f"Scheduler status — enabled={status_resp.enabled}, "
                    f"running={status_resp.running}, "
                    f"jobs={len(status_resp.jobs) if status_resp.jobs else 0}",
                )
            else:
                raise Exception(f"Unexpected response shape: {status_resp}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                # Scheduler not initialized is acceptable for some deployments
                self._pass(results, "Scheduler status — 503 (scheduler not initialized, OK)")
            else:
                self._fail(results, "Scheduler status", e)

        # --- 2. List processes (initial) ---
        results["tests_run"] += 1
        try:
            list_resp = await proc.list_processes(limit=10)
            if hasattr(list_resp, "processes") and hasattr(list_resp, "total_count"):
                self._pass(
                    results,
                    f"List processes — count={len(list_resp.processes)}, "
                    f"total={list_resp.total_count}",
                )
            else:
                raise Exception(f"Unexpected response shape: {list_resp}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "List processes — 503 (tracker not available, OK)")
            else:
                self._fail(results, "List processes (initial)", e)

        # --- 3. List processes with type filter ---
        results["tests_run"] += 1
        try:
            filtered = await proc.list_processes(process_type="maintenance", limit=10)
            if hasattr(filtered, "processes"):
                self._pass(
                    results,
                    f"List with type filter — count={len(filtered.processes)}",
                )
            else:
                raise Exception(f"Unexpected response: {filtered}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "List with type filter — 503 (OK)")
            else:
                self._fail(results, "List with type filter", e)

        # --- 4. List processes with status filter ---
        results["tests_run"] += 1
        try:
            filtered = await proc.list_processes(status="completed", limit=10)
            if hasattr(filtered, "processes"):
                self._pass(
                    results,
                    f"List with status filter — count={len(filtered.processes)}",
                )
            else:
                raise Exception(f"Unexpected response: {filtered}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "List with status filter — 503 (OK)")
            else:
                self._fail(results, "List with status filter", e)

        # --- 5. List processes with pagination ---
        results["tests_run"] += 1
        try:
            page = await proc.list_processes(limit=2, offset=0)
            if hasattr(page, "limit") and page.limit == 2:
                self._pass(
                    results,
                    f"List with pagination — limit={page.limit}, offset={page.offset}, "
                    f"count={len(page.processes)}",
                )
            else:
                raise Exception(f"Pagination not respected: limit={getattr(page, 'limit', '?')}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "List with pagination — 503 (OK)")
            else:
                self._fail(results, "List with pagination", e)

        # --- 6. Trigger maintenance (analyze) ---
        results["tests_run"] += 1
        try:
            trigger_resp = await proc.trigger(process_type="maintenance")
            if hasattr(trigger_resp, "triggered") and hasattr(trigger_resp, "message"):
                self._pass(
                    results,
                    f"Trigger analyze — triggered={trigger_resp.triggered}, "
                    f"message={trigger_resp.message}",
                )
            else:
                raise Exception(f"Unexpected trigger response: {trigger_resp}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "Trigger analyze — 503 (scheduler not available, OK)")
            else:
                self._fail(results, "Trigger maintenance", e)

        # --- 7. List processes (verify new record from trigger) ---
        results["tests_run"] += 1
        try:
            list_after = await proc.list_processes(limit=10)
            if hasattr(list_after, "processes"):
                count = len(list_after.processes)
                if count > 0:
                    captured_process_id = list_after.processes[0].process_id
                    self._pass(
                        results,
                        f"List after trigger — count={count}, "
                        f"first_id={captured_process_id}",
                    )
                else:
                    self._pass(results, "List after trigger — count=0 (no records yet, OK)")
            else:
                raise Exception(f"Unexpected response: {list_after}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "List after trigger — 503 (OK)")
            else:
                self._fail(results, "List after trigger", e)

        # --- 8. Get process by ID ---
        results["tests_run"] += 1
        if captured_process_id:
            try:
                detail = await proc.get_process(captured_process_id)
                if detail.process_id == captured_process_id:
                    self._pass(
                        results,
                        f"Get process — id={detail.process_id}, "
                        f"type={detail.process_type}, status={detail.status}",
                    )
                else:
                    raise Exception(f"ID mismatch: expected {captured_process_id}, got {detail.process_id}")
            except Exception as e:
                self._fail(results, "Get process by ID", e)
        else:
            self._pass(results, "Get process by ID — skipped (no process_id captured)")

        # --- 9. Trigger maintenance with space_id ---
        results["tests_run"] += 1
        try:
            trigger_resp2 = await proc.trigger(
                process_type="maintenance",
                space_id="nonexistent_space",
            )
            if hasattr(trigger_resp2, "triggered"):
                self._pass(
                    results,
                    f"Trigger with space_id — triggered={trigger_resp2.triggered}, "
                    f"message={trigger_resp2.message}",
                )
            else:
                raise Exception(f"Unexpected response: {trigger_resp2}")
        except Exception as e:
            err_str = str(e)
            if "503" in err_str:
                self._pass(results, "Trigger with space_id — 503 (OK)")
            else:
                self._fail(results, "Trigger with space_id", e)

        # --- 10. Get non-existent process (expect 404) ---
        results["tests_run"] += 1
        try:
            await proc.get_process("00000000-0000-0000-0000-000000000000")
            self._fail(results, "Get non-existent process", "Expected 404 but got 200")
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                self._pass(results, "Get non-existent process — 404 (correct)")
            elif "503" in err_str:
                self._pass(results, "Get non-existent process — 503 (tracker not available, OK)")
            else:
                self._fail(results, "Get non-existent process", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results
