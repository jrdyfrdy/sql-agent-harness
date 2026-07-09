from __future__ import annotations

import os
from typing import Any


def _get_float_env(name: str, default: float = 0.0) -> float:
	value = os.getenv(name)
	if value is None:
		return default
	return float(value)


def _require_env(name: str, message: str) -> str:
	value = os.getenv(name)
	if not value:
		raise RuntimeError(message)
	return value


def _default_model(provider: str) -> str:
	return {
		"gemini": "gemini-1.5-pro",
		"openai": "gpt-4o-mini",
		"anthropic": "claude-3-5-sonnet-latest",
		"ollama": "llama3.1",
	}.get(provider, "gemini-1.5-pro")


def build_llm_from_env() -> Any:
	provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
	temperature = _get_float_env("LLM_TEMPERATURE", 0.0)
	model_name = os.getenv("LLM_MODEL") or os.getenv("GEMINI_MODEL") or _default_model(provider)

	if provider == "gemini":
		from langchain_google_genai import ChatGoogleGenerativeAI

		_require_env("GOOGLE_API_KEY", "GOOGLE_API_KEY is required for the Gemini provider.")
		return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)

	if provider == "openai":
		from langchain_openai import ChatOpenAI

		api_key = _require_env("OPENAI_API_KEY", "OPENAI_API_KEY is required for the OpenAI provider.")
		base_url = os.getenv("OPENAI_BASE_URL")
		kwargs: dict[str, Any] = {"model": model_name, "temperature": temperature, "api_key": api_key}
		if base_url:
			kwargs["base_url"] = base_url
		return ChatOpenAI(**kwargs)

	if provider == "anthropic":
		from langchain_anthropic import ChatAnthropic

		api_key = _require_env("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY is required for the Anthropic provider.")
		return ChatAnthropic(model=model_name, temperature=temperature, api_key=api_key)

	if provider == "ollama":
		from langchain_ollama import ChatOllama

		base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
		return ChatOllama(model=model_name, temperature=temperature, base_url=base_url)

	raise RuntimeError(
		"Unsupported LLM_PROVIDER value. Use one of: gemini, openai, anthropic, ollama."
	)