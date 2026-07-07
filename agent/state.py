from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class SqlGeneration(BaseModel):
    query: str = Field(..., description="A DuckDB SQL query that answers the user's question.")
    explanation: str = Field(
        default="",
        description="Short rationale for the generated SQL, useful for debugging and retries.",
    )


class GraphState(TypedDict, total=False):
    question: str
    sql_query: str
    db_result: str
    error_message: str
    retry_count: int
    needs_clarification: bool
    clarification_message: str
    final_answer: str
    generation: SqlGeneration
    messages: Annotated[list, add_messages]


def initial_state(question: str) -> GraphState:
    return {
        "question": question,
        "sql_query": "",
        "db_result": "",
        "error_message": "",
        "retry_count": 0,
        "needs_clarification": False,
        "clarification_message": "",
        "final_answer": "",
        "messages": [],
    }
