"""
Process tracking and scheduling for VitalGraph.

Provides:
- ProcessTracker: CRUD operations on the global process table
- ProcessLockManager: Distributed advisory lock coordination
- ProcessScheduler: Periodic asyncio job runner
- MaintenanceJob: Periodic ANALYZE/VACUUM scoring and execution
"""
