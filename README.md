## Text-to-SQL Agent Harness

Production-oriented Text-to-SQL harness built with LangGraph, DuckDB, FastAPI, and Pydantic. The agent accepts a natural-language ecommerce question, uses Gemini to decide whether clarification is needed, generates DuckDB SQL, executes it in a read-only sandbox, and returns a structured response. It also has a retry loop that can use DuckDB error messages to repair failed queries.

### What it does

- Seeds a local `ecommerce.db` DuckDB database with realistic ecommerce data.
- Exposes a single `POST /ask` endpoint through FastAPI.
- Routes the question through a LangGraph workflow.
- Uses Gemini for clarification decisions, SQL generation, and summarization.
- Executes SQL read-only and summarizes the result.
- Rejects unsafe or multi-statement SQL before it reaches DuckDB.

### Project Structure

```text
sql-agent-harness/
├── data/
│   └── setup_db.py        # Recreates and seeds ecommerce.db
├── agent/
│   ├── state.py           # Typed graph state and SQL generation schema
│   ├── nodes.py           # Ambiguity routing, SQL generation, execution, summarization
│   ├── edges.py           # Route helpers for conditional graph edges
│   └── graph.py           # Graph compilation and demo stream helper
├── main.py                # FastAPI app and /ask endpoint
├── requirements.txt
├── ecommerce.db           # Generated DuckDB database file
├── .env                   # Local environment variables, including API keys
└── .env.sample            # Template for local environment variables
```

### Architecture Overview

The current graph is intentionally small and easy to reason about:

1. `ambiguity_router` checks whether the question is too vague to query reliably.
2. `sql_generator` produces a DuckDB query.
3. `sql_executor` runs the query in read-only mode against `ecommerce.db`.
4. `final_summarizer` turns the JSON result into a concise natural-language answer.

If the executor returns an error, the graph can loop back into SQL generation up to three times. That gives the agent a simple self-correction loop without letting it run forever.

### State Model

The graph state tracks:

- `question`
- `sql_query`
- `db_result`
- `error_message`
- `retry_count`
- `needs_clarification`
- `clarification_message`
- `final_answer`

There is also a structured SQL payload model, `SqlGeneration`, which keeps SQL generation typed instead of relying on free-form text cleanup.

### Gemini-Only Decisioning

The app now requires Gemini at startup. There is no local fallback generator.

Gemini is used to:

- decide whether a question needs clarification
- generate structured DuckDB SQL
- write the final natural-language summary

The graph expects structured Gemini output for the clarification and SQL nodes, which keeps the control flow deterministic without relying on regex cleanup or keyword heuristics.

### Prompt Rules

The SQL generation prompt includes explicit guardrails to reduce common query bugs:

- When querying date or timestamp columns, never use `BETWEEN`.
- Always use `>=` for the start date and `<` for the day after the end date.
- When filtering by string values, always make the comparison case-insensitive.
- Use `LOWER(column_name) = 'value'` or `ILIKE` when appropriate.
- The `status` column in `orders` and `order_facts` only contains lowercase values: `completed`, `pending`, `canceled`, and `refunded`.
- Always filter `status` using lowercase values.

The prompt also includes a few-shot example for the most common date/string filter pattern:

```text
User Question: What was the total quantity of Accessories sold to US customers in July 2024?
Expected SQL:
SELECT
    SUM(quantity) AS total_accessories_qty
FROM
    order_facts
WHERE
    category = 'Accessories'
    AND customer_country = 'US'
    AND LOWER(status) = 'completed'
    AND order_date >= '2024-07-01'
    AND order_date < '2024-08-01';
```

### Security Model

The executor is intentionally conservative:

- only a single `SELECT` or `WITH` statement is allowed
- multi-statement SQL is rejected
- non-read-only statements like `DROP`, `INSERT`, or `UPDATE` are blocked before the database opens
- DuckDB is opened in `read_only=True` mode

### Requirements

- Python 3.14+
- DuckDB
- FastAPI
- Uvicorn
- Pydantic 2
- LangGraph
- LangChain Core
- langchain-google-genai
- python-dotenv

### Installation

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
venv\Scripts\activate
pip install -r requirements.txt
```

This repository already includes a `venv/` folder, so on Windows you can also use:

```bash
venv\Scripts\python.exe -m pip install -r requirements.txt
```

If you run `python main.py` with a Python interpreter that does not have the project dependencies installed, you will see `ModuleNotFoundError: No module named 'fastapi'`. In that case, activate the repo venv or run the app with `venv\Scripts\python.exe main.py`.

### Database Setup

Generate the local DuckDB database:

```bash
python data/setup_db.py
```

By default this creates `ecommerce.db` in the project root. You can override the output path with `--db-path`.

### Running the API

Start the FastAPI app with Uvicorn:

```bash
uvicorn main:app --reload
```

Or run the module directly:

```bash
venv\Scripts\python.exe main.py
```

### API Usage

#### `GET /health`

Returns a simple readiness check:

```json
{ "status": "ok" }
```

#### `POST /ask`

Request:

```json
{
  "question": "Show completed order revenue for July 2024"
}
```

Response fields:

- `question`
- `needs_clarification`
- `clarification_message`
- `sql_query`
- `db_result`
- `error_message`
- `retry_count`
- `final_answer`

Example response:

```json
{
  "question": "Show completed order revenue for July 2024",
  "needs_clarification": false,
  "clarification_message": "",
  "sql_query": "SELECT ROUND(SUM(line_total), 2) AS revenue FROM order_facts WHERE status = 'completed';",
  "db_result": "[{\"revenue\":1910.77}]",
  "error_message": "",
  "retry_count": 0,
  "final_answer": "Question: Show completed order revenue for July 2024\nResult: [{\"revenue\":1910.77}]"
}
```

### Environment Variables

Create a `.env` file in the project root when you want to configure local overrides. The easiest path is to copy `.env.sample` and fill in the values you want to use.

Common values:

```env
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-1.5-pro
ECOMMERCE_DB_PATH=./ecommerce.db
APP_TITLE=Text-to-SQL Agent
APP_VERSION=0.1.0
APP_HOST=127.0.0.1
APP_PORT=8000
APP_RELOAD=false
```

`GOOGLE_API_KEY` is required now. If it is missing, the app will raise a startup error instead of falling back to a local generator.

### Mock Data

The seeded database includes:

- customers
- products
- orders
- order items
- a derived `order_facts` view for easier analytical queries

The sample data intentionally includes:

- active and inactive customers
- active and inactive products
- completed, pending, canceled, and refunded orders
- low-stock products
- multiple line items per order

That mix helps the agent exercise joins, grouping, filtering, and error correction.

### Development Notes

- `ecommerce.db` is generated locally and ignored by git.
- The codebase is organized so the graph can use a live Gemini model without changing the FastAPI surface.
- The current graph is intentionally minimal; it is a strong base for adding richer prompt templates, structured model calls, and semantic caching later.

### Roadmap

Planned next improvements:

- refine Gemini prompts for clarification and SQL generation
- add richer SQL validation and result formatting
- add caching for repeated questions
- add more comprehensive tests around edge cases and query repair

### License

See [LICENSE](LICENSE).
