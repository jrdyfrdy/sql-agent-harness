from __future__ import annotations
from pathlib import Path
from typing import Any, Protocol, TypeVar, List, Dict
from pydantic import BaseModel, Field
from .state import GraphState, SqlGeneration
import duckdb
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MAX_RETRIES = 3
READ_ONLY_PREFIXES = ("select", "with")


class SupportsInvoke(Protocol):
    def invoke(self, input: Any, config: dict[str, Any] | None = None) -> Any: ...


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ClarificationDecision(BaseModel):
    needs_clarification: bool = Field(..., description="Whether the question needs a clarification before SQL generation.")
    clarification_message: str = Field(
        default="",
        description="A concise clarification request shown when the question is too vague.",
    )


def _invoke_structured(llm: SupportsInvoke, schema: type[StructuredModel], prompt: str) -> StructuredModel:
    structured_llm = llm.with_structured_output(schema) if hasattr(llm, "with_structured_output") else llm
    response = structured_llm.invoke(prompt)

    if isinstance(response, schema):
        return response
    if isinstance(response, dict):
        return schema.model_validate(response)
    if isinstance(response, str):
        return schema.model_validate_json(response)
    return schema.model_validate(response)


def ambiguity_router(state: GraphState, llm: SupportsInvoke, db_config: Dict[str, Any]) -> GraphState:
    question = state.get("question", "")
    domain = db_config.get("domain_context", "business")
    
    prompt = (
        f"You are deciding whether a {domain} analytics question is precise enough for SQL generation.\n"
        "Return a structured object with fields 'needs_clarification' and 'clarification_message'.\n"
        "Ask for clarification when the question is vague, underspecified, or missing a metric, time range, or entity.\n"
        "If no clarification is needed, set 'needs_clarification' to false and 'clarification_message' to an empty string.\n"
        f"Question: {question}"
    )
    decision = ClarificationDecision.model_validate(_invoke_structured(llm, ClarificationDecision, prompt))

    return {
        "needs_clarification": decision.needs_clarification,
        "clarification_message": decision.clarification_message,
    }


def build_sql_prompt(question: str, db_config: Dict[str, Any], error_message: str = "") -> str:
    retry_guidance = ""
    if error_message:
        retry_guidance = (
            "\nThe previous SQL failed. Fix the query using this DuckDB error trace:\n"
            f"{error_message}\n"
        )

    domain = db_config.get("domain_context", "business")
    schema_hint = db_config.get("schema_hint", "")
    rules = "\n".join([f"- {rule}" for rule in (db_config.get("business_rules") or [])])
    few_shot = db_config.get("few_shot_examples", "")

    return (
        f"You are a senior analytics engineer writing DuckDB SQL for a {domain} schema.\n"
        "Follow these rules exactly:\n"
        f"{rules}\n"
        "- Output Format: Return ONLY a valid JSON object with exactly two keys: 'query' (the SQL string) and 'explanation' (a brief explanation of the logic). Do not wrap the JSON or SQL in markdown fences.\n"
        "- Use only read-only SQL. Avoid INSERT, UPDATE, DELETE, DROP, and CREATE.\n"
        "\nFew-shot examples:\n"
        f"{few_shot}\n"
        f"\nSchema reference:\n{schema_hint}\n"
        f"Question: {question}\n"
        f"{retry_guidance}"
    )


def sql_generator(state: GraphState, llm: SupportsInvoke, db_config: Dict[str, Any]) -> GraphState:
    question = state.get("question", "")
    error_message = state.get("error_message", "")

    prompt = build_sql_prompt(question, db_config, error_message)
    generation = SqlGeneration.model_validate(_invoke_structured(llm, SqlGeneration, prompt))

    return {"sql_query": generation.query.strip(), "generation": generation}


def normalize_sql(sql_query: str) -> str:
    result = []
    i = 0
    n = len(sql_query)
    in_single_quote = False
    in_double_quote = False

    while i < n:
        if in_single_quote:
            if sql_query[i] == "'" and (i == 0 or sql_query[i-1] != "\\"):
                in_single_quote = False
            result.append('x')
            i += 1
        elif in_double_quote:
            if sql_query[i] == '"' and (i == 0 or sql_query[i-1] != "\\"):
                in_double_quote = False
            result.append('x')
            i += 1
        else:
            if sql_query[i:i+2] == '--':
                i += 2
                while i < n and sql_query[i] != '\n':
                    i += 1
            elif sql_query[i:i+2] == '/*':
                i += 2
                while i < n and sql_query[i:i+2] != '*/':
                    i += 1
                i += 2
            elif sql_query[i] == "'":
                in_single_quote = True
                result.append("'")
                i += 1
            elif sql_query[i] == '"':
                in_double_quote = True
                result.append('"')
                i += 1
            else:
                result.append(sql_query[i])
                i += 1

    normalized = "".join(result)
    return normalized.strip().rstrip(";").strip()


def is_read_only_sql(sql_query: str) -> bool:
    normalized = normalize_sql(sql_query).lower()
    if not normalized:
        return False
    if ";" in normalized:
        return False
    return normalized.startswith(READ_ONLY_PREFIXES)


def validate_sql_query(sql_query: str) -> str:
    normalized = normalize_sql(sql_query)
    if not normalized:
        raise ValueError("No SQL query was generated.")
    if not is_read_only_sql(normalized):
        raise ValueError("Only a single read-only SELECT or WITH statement is allowed.")
    return sql_query


def sql_executor(state: GraphState, db_path: Path | None = None) -> GraphState:
    try:
        sql_query = validate_sql_query(state.get("sql_query", ""))
    except ValueError as exc:
        return {"error_message": str(exc), "db_result": "", "retry_count": state.get("retry_count", 0) + 1}

    if db_path is None:
        return {
            "db_result": "",
            "error_message": "Database path was not provided to the executor.",
            "retry_count": state.get("retry_count", 0) + 1,
        }

    if not db_path.exists():
        return {
            "db_result": "",
            "error_message": f"Database file not found: {db_path}",
            "retry_count": state.get("retry_count", 0) + 1,
        }

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        result = connection.execute(sql_query).fetchdf()
        return {
            "db_result": result.to_json(orient="records", date_format="iso"),
            "error_message": "",
            "retry_count": state.get("retry_count", 0),
        }
    except Exception as exc:  # DuckDB exceptions are surfaced as Python exceptions.
        return {
            "db_result": "",
            "error_message": str(exc),
            "retry_count": state.get("retry_count", 0) + 1,
        }
    finally:
        connection.close()


def final_summarizer(state: GraphState, llm: SupportsInvoke, db_config: Dict[str, Any]) -> GraphState:
    question = state.get("question", "")
    db_result = state.get("db_result", "")
    domain = db_config.get("domain_context", "business")

    prompt = (
        f"Write a concise business answer for this {domain} question.\n"
        f"Question: {question}\n"
        f"Data: {db_result}\n"
    )
    response = llm.invoke(prompt)

    content = response.content if hasattr(response, "content") else response

    if isinstance(content, str):
        final_answer = content
    elif isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if (block_type == "text" or block_type is None) and "text" in block:
                    text_parts.append(block["text"])
            elif isinstance(block, str):
                text_parts.append(block)
        final_answer = "".join(text_parts)
    else:
        final_answer = str(content)

    return {"final_answer": final_answer.strip()}


def should_retry(state: GraphState) -> bool:
    return bool(state.get("error_message")) and state.get("retry_count", 0) < MAX_RETRIES


def circuit_breaker_triggered(state: GraphState) -> bool:
    return bool(state.get("error_message")) and state.get("retry_count", 0) >= MAX_RETRIES