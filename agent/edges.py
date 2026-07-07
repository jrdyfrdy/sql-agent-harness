from __future__ import annotations

from .nodes import circuit_breaker_triggered, should_retry
from .state import GraphState


def route_after_ambiguity(state: GraphState) -> str:
    return "clarify" if state.get("needs_clarification") else "generate"


def route_after_executor(state: GraphState) -> str:
    if circuit_breaker_triggered(state):
        return "end"
    if should_retry(state):
        return "retry"
    return "summarize"
