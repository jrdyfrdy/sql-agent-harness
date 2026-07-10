# main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from agent.graph import build_graph
from agent.llm import build_llm_from_env
from agent.state import initial_state
from config import DB_CONFIG # Import your configuration


PROJECT_ROOT = Path(__file__).resolve().parent


def _get_bool_env(name: str, default: bool = False) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


class AskRequest(BaseModel):
    # Description updated to be domain agnostic
	question: str = Field(..., min_length=1, description="Natural language question about the data.")


class AskResponse(BaseModel):
	question: str
	needs_clarification: bool
	clarification_message: str = ""
	sql_query: str = ""
	db_result: str = ""
	error_message: str = ""
	retry_count: int = 0
	final_answer: str = ""


def create_app() -> FastAPI:
	load_dotenv()

	database_path = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "ecommerce.db")))
	app_title = os.getenv("APP_TITLE", "Text-to-SQL Agent")
	app_version = os.getenv("APP_VERSION", "0.1.0")
	app_host = os.getenv("APP_HOST", "127.0.0.1")
	app_port = int(os.getenv("APP_PORT", "8000"))
	app_reload = _get_bool_env("APP_RELOAD", False)
	llm = build_llm_from_env()
    
	graph = build_graph(db_config=DB_CONFIG, db_path=database_path, llm=llm)

	app = FastAPI(title=app_title, version=app_version)
	app.state.graph = graph
	app.state.server_host = app_host
	app.state.server_port = app_port
	app.state.server_reload = app_reload

	@app.get("/health")
	def health_check() -> dict[str, str]:
		return {"status": "ok"}

	@app.post("/ask", response_model=AskResponse)
	def ask(request: AskRequest) -> AskResponse:
		state = initial_state(request.question)
		result = app.state.graph.invoke(state)
		return AskResponse(
			question=request.question,
			needs_clarification=bool(result.get("needs_clarification", False)),
			clarification_message=result.get("clarification_message", ""),
			sql_query=result.get("sql_query", ""),
			db_result=result.get("db_result", ""),
			error_message=result.get("error_message", ""),
			retry_count=int(result.get("retry_count", 0)),
			final_answer=result.get("final_answer", ""),
		)

	return app


app = create_app()


if __name__ == "__main__":
	import uvicorn

	uvicorn.run(
		"main:app",
		host=os.getenv("APP_HOST", "127.0.0.1"),
		port=int(os.getenv("APP_PORT", "8000")),
		reload=_get_bool_env("APP_RELOAD", False),
	)