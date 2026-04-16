from typing import AsyncIterator

from src.app.services.model_gateway import get_model_gateway
from src.app.services.prompts import (
    REPLY_SYSTEM_PROMPT,
    REPLY_USER_PROMPT_TEMPLATE,
)

MODEL_UNAVAILABLE_MESSAGE = "模型暂不可用，请稍后重试。"


def _format_recent_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "(无)"
    lines: list[str] = []
    for item in history:
        role = item.get("role", "")
        content = item.get("content", "").strip()
        if not content:
            continue
        if role == "user":
            role_label = "用户"
        elif role == "assistant":
            role_label = "助手"
        else:
            role_label = role or "系统"
        lines.append(f"{role_label}: {content}")
    return "\n".join(lines) if lines else "(无)"


def build_reply_user_prompt(
    *,
    message: str,
    recent_history: list[dict[str, str]] | None = None,
    history_rounds: int = 0,
) -> str:
    history_text = _format_recent_history(recent_history or [])
    return REPLY_USER_PROMPT_TEMPLATE.format(
        user_message=message,
        recent_history=history_text,
        history_rounds=history_rounds,
    )


async def stream_reply(
    message: str,
    *,
    recent_history: list[dict[str, str]] | None = None,
    history_rounds: int = 0,
) -> AsyncIterator[str]:
    gateway = get_model_gateway()
    user_prompt = build_reply_user_prompt(
        message=message,
        recent_history=recent_history,
        history_rounds=history_rounds,
    )
    emitted = False
    try:
        async for piece in gateway.stream_reply_text(
            system_prompt=REPLY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        ):
            if not piece:
                continue
            emitted = True
            yield piece
    except Exception:
        emitted = False

    if not emitted:
        yield MODEL_UNAVAILABLE_MESSAGE


async def render_reply(
    message: str,
    *,
    recent_history: list[dict[str, str]] | None = None,
    history_rounds: int = 0,
) -> str:
    chunks: list[str] = []
    async for piece in stream_reply(
        message,
        recent_history=recent_history,
        history_rounds=history_rounds,
    ):
        chunks.append(piece)
    body = "".join(chunks).strip()
    if not body:
        return MODEL_UNAVAILABLE_MESSAGE
    return body
