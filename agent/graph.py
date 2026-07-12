from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from .edges import route_after_ambiguity, route_after_executor
from .nodes import ambiguity_router, final_summarizer, sql_executor, sql_generator
from .state import GraphState, initial_state
from .llm import build_llm_from_env

def build_graph(db_config: Dict[str, Any], db_path: Path | None = None, llm: Any | None = None):
    if llm is None:
        raise RuntimeError("A language model (LLM) is required to build the graph.")

    workflow = StateGraph(GraphState)

    workflow.add_node("ambiguity_router", _ambiguity_node(llm, db_config))
    workflow.add_node("sql_generator", _sql_generation_node(llm, db_config))
    workflow.add_node("sql_executor", _executor_node(db_path))
    workflow.add_node("final_summarizer", _summarizer_node(llm, db_config))

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


def _ambiguity_node(llm: Any, db_config: Dict[str, Any]):
    def node(state: GraphState) -> GraphState:
        return ambiguity_router(state, llm=llm, db_config=db_config)

    return node


def _sql_generation_node(llm: Any, db_config: Dict[str, Any]):
    def node(state: GraphState) -> GraphState:
        return sql_generator(state, llm=llm, db_config=db_config)

    return node


def _summarizer_node(llm: Any, db_config: Dict[str, Any]):
    def node(state: GraphState) -> GraphState:
        return final_summarizer(state, llm=llm, db_config=db_config)

    return node


def stream_demo(question: str, db_config: Dict[str, Any], db_path: Path | None = None) -> list[dict[str, Any]]:
    """Run the graph once and stream its events to stdout.

    Intended for local, terminal-based debugging via `python -m agent.graph`.
    Requires LLM credentials configured in the environment (see .env.sample)
    for build_llm_from_env() to resolve a provider — e.g. GOOGLE_API_KEY for
    the default `gemini` provider, or OPENAI_API_KEY / ANTHROPIC_API_KEY when
    LLM_PROVIDER is set accordingly.
    """
    llm = build_llm_from_env()
    graph = build_graph(db_config=db_config, db_path=db_path, llm=llm)
    state = initial_state(question)
    events: list[dict[str, Any]] = []

    for event in graph.stream(state):
        events.append(event)
        print(event)

    return events

if __name__ == "__main__":
    from dotenv import load_dotenv

    from config import load_db_config

    load_dotenv()

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    db_config = load_db_config(PROJECT_ROOT / "db_config.yaml")

    stream_demo(
        question="How many active customers are there?",
        db_config=db_config,
        db_path=PROJECT_ROOT / "ecommerce.db",
    )