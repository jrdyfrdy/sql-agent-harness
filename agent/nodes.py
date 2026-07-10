from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeVar

import duckdb
from pydantic import BaseModel, Field

from .state import GraphState, SqlGeneration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "ecommerce.db"

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


def ambiguity_router(state: GraphState, llm: SupportsInvoke) -> GraphState:
    question = state.get("question", "")
    prompt = (
        "You are deciding whether an ecommerce analytics question is precise enough for SQL generation.\n"
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


def build_sql_prompt(question: str, schema_hint: str, error_message: str = "") -> str:
    retry_guidance = ""
    if error_message:
        retry_guidance = (
            "\nThe previous SQL failed. Fix the query using this DuckDB error trace:\n"
            f"{error_message}\n"
        )

    return (
        "You are a senior analytics engineer writing DuckDB SQL for an ecommerce schema.\n"
        "Follow these rules exactly:\n"
        "- Rule for Dates and Timestamps: When querying date or timestamp columns, NEVER use BETWEEN.\n"
        "  Always use >= for the start date and < for the day after the end date.\n"
        "- Rule for String Filtering: Never assume capitalization. When filtering by string values, always ensure case-insensitivity by using LOWER(column_name) = 'lowercased_value'.\n"
        "- Rule for Aggregations: When using aggregate functions like SUM(), AVG(), or MAX(), always wrap them in COALESCE(..., 0) to ensure a 0 is returned instead of NULL if no rows match.\n"
        "- Rule for Status Codes: The status column in the orders and order_facts tables only contains lowercase values:\n"
        "  ['completed', 'pending', 'canceled', 'refunded']. Always use lowercase when filtering on this column.\n"
        "- Output Format: Return ONLY a valid JSON object with exactly two keys: 'query' (the SQL string) and 'explanation' (a brief explanation of the logic). Do not wrap the JSON or SQL in markdown fences.\n"
        "- Use only read-only SQL. Avoid INSERT, UPDATE, DELETE, DROP, and CREATE.\n"
        "\nFew-shot example:\n"
        "User Question: What was the total quantity of Accessories sold to US customers in July 2024?\n"
        "Expected JSON Response:\n"
        "{\n"
        "  \"query\": \"SELECT COALESCE(SUM(quantity), 0) AS total_accessories_qty FROM order_facts WHERE LOWER(category) = 'accessories' AND LOWER(customer_country) = 'us' AND LOWER(status) = 'completed' AND order_date >= '2024-07-01' AND order_date < '2024-08-01'\",\n"
        "  \"explanation\": \"Calculates the total quantity by summing the quantity column, coercing nulls to 0. Filters are applied case-insensitively using LOWER(), and date boundaries are set for the month of July 2024.\"\n"
        "}\n"
        f"\nSchema reference:\n{schema_hint}\n"
        f"Question: {question}\n"
        f"{retry_guidance}"
    )


def schema_hint() -> str:
    return """
tables:
  customers(customer_id, first_name, last_name, email, country, created_at, is_active)
  products(product_id, product_name, category, unit_price, unit_cost, stock_qty, is_active)
  orders(order_id, customer_id, order_date, status, payment_method, shipping_country)
  order_items(order_item_id, order_id, product_id, quantity, unit_price, discount_pct)
view:
  order_facts(order_id, order_date, status, payment_method, shipping_country, customer_id,
              first_name, last_name, customer_country, product_id, product_name, category,
              quantity, unit_price, discount_pct, line_total)
""".strip()


def sql_generator(state: GraphState, llm: SupportsInvoke) -> GraphState:
    question = state.get("question", "")
    error_message = state.get("error_message", "")

    prompt = build_sql_prompt(question, schema_hint(), error_message)
    generation = SqlGeneration.model_validate(_invoke_structured(llm, SqlGeneration, prompt))

    return {"sql_query": generation.query.strip(), "generation": generation}


def normalize_sql(sql_query: str) -> str:
    return sql_query.strip().rstrip(";").strip()


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
    return normalized


def sql_executor(state: GraphState, db_path: Path | None = None) -> GraphState:
    try:
        sql_query = validate_sql_query(state.get("sql_query", ""))
    except ValueError as exc:
        return {"error_message": str(exc), "db_result": "", "retry_count": state.get("retry_count", 0) + 1}

    database_path = db_path or DEFAULT_DB_PATH
    if not database_path.exists():
        return {
            "db_result": "",
            "error_message": f"Database file not found: {database_path}",
            "retry_count": state.get("retry_count", 0) + 1,
        }

    connection = duckdb.connect(str(database_path), read_only=True)
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


def final_summarizer(state: GraphState, llm: SupportsInvoke) -> GraphState:
    question = state.get("question", "")
    db_result = state.get("db_result", "")

    prompt = (
        "Write a concise business answer for this ecommerce question.\n"
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
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif "text" in block and block.get("type") != "thinking":
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
