import inspect
from typing import Any

from langchain_openai import ChatOpenAI

from src.app.config import settings


def _build_openai_compatible_kwargs() -> dict[str, Any]:
    params = inspect.signature(ChatOpenAI).parameters
    kwargs: dict[str, Any] = {
        "timeout": float(settings.model_timeout_sec),
    }

    if "api_key" in params:
        kwargs["api_key"] = settings.model_api_key
    else:
        kwargs["openai_api_key"] = settings.model_api_key

    if "base_url" in params:
        kwargs["base_url"] = settings.model_api_base
    else:
        kwargs["openai_api_base"] = settings.model_api_base

    return kwargs


def get_route_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.route_model_name,
        temperature=settings.route_temperature,
        max_tokens=settings.route_max_tokens,
        streaming=False,
        **_build_openai_compatible_kwargs(),
    )


def get_response_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.response_model_name,
        temperature=settings.response_temperature,
        max_tokens=settings.response_max_tokens,
        streaming=True,
        **_build_openai_compatible_kwargs(),
    )
