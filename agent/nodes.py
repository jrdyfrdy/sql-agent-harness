from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import duckdb

from .state import GraphState, SqlGeneration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "ecommerce.db"

MAX_RETRIES = 3
READ_ONLY_PREFIXES = ("select", "with")


class SupportsInvoke(Protocol):
    def invoke(self, input: Any, config: dict[str, Any] | None = None) -> Any: ...


@dataclass(frozen=True)
class ClarificationRule:
    keywords: tuple[str, ...] = (
        "something",
        "stuff",
        "anything",
        "whatever",
        "best",
        "top",
        "popular",
        "interesting",
        "recent",
    )

    def is_ambiguous(self, question: str) -> bool:
        normalized = question.strip().lower()
        if len(normalized.split()) < 4:
            return True
        return any(keyword in normalized for keyword in self.keywords)


def ambiguity_router(state: GraphState) -> GraphState:
    question = state.get("question", "")
    rule = ClarificationRule()

    if rule.is_ambiguous(question):
        return {
            "needs_clarification": True,
            "clarification_message": (
                "Please specify the metric, entity, and time range so I can build a precise SQL query. "
                "For example: 'Show completed order revenue by customer for July 2024.'"
            ),
        }

    return {
        "needs_clarification": False,
        "clarification_message": "",
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
        "Return only a valid structured object with fields 'query' and 'explanation'.\n"
        "Do not wrap the SQL in markdown fences.\n"
        "Use only read-only SQL. Avoid INSERT, UPDATE, DELETE, DROP, and CREATE.\n"
        f"Schema reference:\n{schema_hint}\n"
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


def sql_generator(state: GraphState, llm: SupportsInvoke | None = None) -> GraphState:
    question = state.get("question", "")
    error_message = state.get("error_message", "")

    if llm is None:
        sql_text = _fallback_sql(question)
        return {
            "sql_query": sql_text,
            "generation": SqlGeneration(query=sql_text, explanation="Fallback SQL generated without an LLM."),
        }

    prompt = build_sql_prompt(question, schema_hint(), error_message)
    structured = llm.invoke(prompt)

    if isinstance(structured, SqlGeneration):
        generation = structured
    elif isinstance(structured, dict):
        generation = SqlGeneration.model_validate(structured)
    else:
        generation = SqlGeneration.model_validate({"query": str(structured), "explanation": ""})

    return {
        "sql_query": generation.query.strip(),
        "generation": generation,
    }


def _fallback_sql(question: str) -> str:
    normalized = question.lower()
    if "revenue" in normalized:
        return (
            "SELECT ROUND(SUM(line_total), 2) AS revenue "
            "FROM order_facts "
            "WHERE status = 'completed';"
        )
    if "customer" in normalized and "order" in normalized:
        return (
            "SELECT customer_id, first_name, last_name, COUNT(DISTINCT order_id) AS order_count "
            "FROM order_facts "
            "GROUP BY customer_id, first_name, last_name "
            "ORDER BY order_count DESC, customer_id;"
        )
    return "SELECT * FROM order_facts LIMIT 10;"


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


def final_summarizer(state: GraphState, llm: SupportsInvoke | None = None) -> GraphState:
    question = state.get("question", "")
    db_result = state.get("db_result", "")

    if llm is None:
        return {
            "final_answer": f"Question: {question}\nResult: {db_result}",
        }

    prompt = (
        "Write a concise business answer for this ecommerce question.\n"
        f"Question: {question}\n"
        f"Data: {db_result}\n"
    )
    response = llm.invoke(prompt)
    return {"final_answer": str(response)}


def should_retry(state: GraphState) -> bool:
    return bool(state.get("error_message")) and state.get("retry_count", 0) < MAX_RETRIES


def circuit_breaker_triggered(state: GraphState) -> bool:
    return bool(state.get("error_message")) and state.get("retry_count", 0) >= MAX_RETRIES
