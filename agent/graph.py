from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from .edges import route_after_ambiguity, route_after_executor
from .nodes import ambiguity_router, final_summarizer, sql_executor, sql_generator
from .state import GraphState, initial_state


def build_graph(db_path: Path | None = None, llm: Any | None = None):
    if llm is None:
        raise RuntimeError("A Gemini LLM is required to build the graph.")

    workflow = StateGraph(GraphState)

    workflow.add_node("ambiguity_router", _ambiguity_node(llm))
    workflow.add_node("sql_generator", _sql_generation_node(llm))
    workflow.add_node("sql_executor", _executor_node(db_path))
    workflow.add_node("final_summarizer", _summarizer_node(llm))

    workflow.add_edge(START, "ambiguity_router")
    workflow.add_conditional_edges(
        "ambiguity_router",
        route_after_ambiguity,
        {
            "clarify": END,
            "generate": "sql_generator",
        },
    )
    workflow.add_edge("sql_generator", "sql_executor")
    workflow.add_conditional_edges(
        "sql_executor",
        route_after_executor,
        {
            "retry": "sql_generator",
            "summarize": "final_summarizer",
            "end": END,
        },
    )
    workflow.add_edge("final_summarizer", END)

    return workflow.compile()


def _executor_node(db_path: Path | None):
    def executor(state: GraphState) -> GraphState:
        return sql_executor(state, db_path=db_path)

    return executor


def _ambiguity_node(llm: Any):
    def node(state: GraphState) -> GraphState:
        return ambiguity_router(state, llm=llm)

    return node


def _sql_generation_node(llm: Any):
    def node(state: GraphState) -> GraphState:
        return sql_generator(state, llm=llm)

    return node


def _summarizer_node(llm: Any):
    def node(state: GraphState) -> GraphState:
        return final_summarizer(state, llm=llm)

    return node


def stream_demo(question: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    graph = build_graph(db_path=db_path)
    state = initial_state(question)
    events: list[dict[str, Any]] = []

    for event in graph.stream(state):
        events.append(event)
        print(event)

    return events


if __name__ == "__main__":
    stream_demo("Show completed order revenue by customer for July 2024")
