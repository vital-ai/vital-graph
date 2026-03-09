"""Handler for KIND_NULL — empty result set."""

from __future__ import annotations

from .ir import PlanV2
from .emit_context import EmitContext


def emit_null(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an empty result set."""
    return "SELECT 1 WHERE FALSE"
