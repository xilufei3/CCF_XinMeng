from dataclasses import dataclass
from typing import AsyncIterator, Literal

from src.app.services.model_gateway import get_model_gateway
from src.app.services.prompts import (
    INTENT_SYSTEM_PROMPT,
    INTENT_USER_PROMPT_TEMPLATE,
    REPLY_SYSTEM_PROMPT,
    REPLY_USER_PROMPT_TEMPLATE,
)

Scene = Literal["knowledge", "emotion", "advice", "service", "offtopic"]
MODEL_UNAVAILABLE_MESSAGE = "模型暂不可用，请稍后重试。"


@dataclass(frozen=True)
class RouteResult:
    intent: Scene


VALID_SCENES = {"knowledge", "emotion", "advice", "service", "offtopic"}


def _as_scene(value: str) -> Scene:
    if value in VALID_SCENES:
        return value  # type: ignore[return-value]
    return "knowledge"


def _model_unavailable_route() -> RouteResult:
    return RouteResult(
        intent="knowledge",
    )


async def classify_intent(
    user_message: str,
) -> RouteResult:
    gateway = get_model_gateway()
    user_prompt = INTENT_USER_PROMPT_TEMPLATE.format(
        user_message=user_message,
    )
    try:
        payload = await gateway.generate_intent_json(
            system_prompt=INTENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception:
        return _model_unavailable_route()

    try:
        intent = _as_scene(str(payload.get("intent", "knowledge")).strip().lower())
        return RouteResult(
            intent=intent,
        )
    except Exception:
        return _model_unavailable_route()


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


async def stream_scene_reply(
    scene: Scene,
    message: str,
    *,
    recent_history: list[dict[str, str]] | None = None,
    history_rounds: int = 0,
) -> AsyncIterator[str]:
    del scene

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


async def render_scene_reply(
    scene: Scene,
    message: str,
    *,
    recent_history: list[dict[str, str]] | None = None,
    history_rounds: int = 0,
) -> str:
    chunks: list[str] = []
    async for piece in stream_scene_reply(
        scene,
        message,
        recent_history=recent_history,
        history_rounds=history_rounds,
    ):
        chunks.append(piece)
    body = "".join(chunks).strip()
    if not body:
        return MODEL_UNAVAILABLE_MESSAGE
    return body
