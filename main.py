from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from agent.graph import build_graph
from agent.state import initial_state


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "ecommerce.db"


class AskRequest(BaseModel):
	question: str = Field(..., min_length=1, description="Natural language question about the ecommerce data.")


class AskResponse(BaseModel):
	question: str
	needs_clarification: bool
	clarification_message: str = ""
	sql_query: str = ""
	db_result: str = ""
	error_message: str = ""
	retry_count: int = 0
	final_answer: str = ""


def _build_gemini_llm() -> ChatGoogleGenerativeAI:
	api_key = os.getenv("GOOGLE_API_KEY")
	if not api_key:
		raise RuntimeError("GOOGLE_API_KEY is required. Add it to the project .env file before starting the app.")

	model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
	return ChatGoogleGenerativeAI(model=model_name, temperature=0)


def create_app() -> FastAPI:
	load_dotenv()

	database_path = Path(os.getenv("ECOMMERCE_DB_PATH", DEFAULT_DB_PATH))
	llm = _build_gemini_llm()
	graph = build_graph(db_path=database_path, llm=llm)

	app = FastAPI(title="Text-to-SQL Agent", version="0.1.0")
	app.state.graph = graph

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

	uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
