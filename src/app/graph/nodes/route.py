import json
import logging
import re
from typing import Any
from time import perf_counter

from pydantic import BaseModel, Field

from src.app.graph.state import GraphState
from src.app.prompts.route import ROUTE_SYSTEM_PROMPT
from src.app.services.llm import get_route_llm

logger = logging.getLogger(__name__)
MAX_REASON_LEN = 30
DEFAULT_NON_RETRIEVAL_REASON = "默认不检索:路由结果格式异常"


class RouteDecision(BaseModel):
    need_retrieval: bool = Field(description="是否需要检索星萌乐读专业知识库")
    reason: str = Field(description="简短的判断原因, 不超过30字")


_route_chain = None


def _get_route_chain():
    global _route_chain
    if _route_chain is None:
        _route_chain = get_route_llm().with_structured_output(
            RouteDecision,
            method="json_mode",
            include_raw=True,
        )
    return _route_chain


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_to_text(item) for item in content)
    if isinstance(content, dict):
        # OpenAI-compatible providers may return block items with text/content/value.
        for key in ("text", "content", "value"):
            value = content.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                return value
            if isinstance(value, (list, dict)):
                nested = _content_to_text(value)
                if nested:
                    return nested
        return ""

    # Some SDKs return typed blocks (e.g. TextBlock) instead of dicts.
    for attr in ("text", "content", "value"):
        value = getattr(content, attr, None)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, (list, dict)):
            nested = _content_to_text(value)
            if nested:
                return nested

    return str(content)


def _strip_markdown_fence(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith("```"):
        return normalized

    lines = normalized.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _strip_json_language_tag(text: str) -> str:
    normalized = text.lstrip()
    if normalized[:4].lower() != "json":
        return normalized
    suffix = normalized[4:]
    if suffix and not suffix[0].isspace():
        # e.g. "json_object" should not be altered.
        return normalized
    return suffix.lstrip()


def _extract_first_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in route raw output")

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    raise ValueError("unbalanced JSON object in route raw output")


def _append_unique(candidates: list[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in candidates:
        candidates.append(normalized)


def _build_parse_candidates(raw_text: str) -> list[str]:
    candidates: list[str] = []
    normalized = raw_text.strip()

    _append_unique(candidates, normalized)
    _append_unique(candidates, _strip_json_language_tag(normalized))

    fence_stripped = _strip_markdown_fence(normalized)
    _append_unique(candidates, fence_stripped)
    _append_unique(candidates, _strip_json_language_tag(fence_stripped))

    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", normalized, re.IGNORECASE)
    if fenced_match:
        fenced_body = fenced_match.group(1).strip()
        _append_unique(candidates, fenced_body)
        _append_unique(candidates, _strip_json_language_tag(fenced_body))

    # Try extracting the first JSON object from each intermediate variant.
    snapshot = list(candidates)
    for candidate in snapshot:
        try:
            extracted = _extract_first_balanced_object(candidate)
            _append_unique(candidates, extracted)
        except Exception:
            continue

    return candidates


def _preview(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _clip_reason(reason: str, fallback: str) -> str:
    normalized = " ".join(str(reason).split()).strip()
    if not normalized:
        return fallback
    return normalized[:MAX_REASON_LEN]


def _sanitize_decision(decision: RouteDecision, fallback_reason: str) -> RouteDecision:
    return RouteDecision(
        need_retrieval=bool(decision.need_retrieval),
        reason=_clip_reason(decision.reason, fallback_reason),
    )


def _default_non_retrieval_decision(reason: str = DEFAULT_NON_RETRIEVAL_REASON) -> RouteDecision:
    return RouteDecision(
        need_retrieval=False,
        reason=_clip_reason(reason, DEFAULT_NON_RETRIEVAL_REASON),
    )


def _parse_decision_from_keywords(raw_text: str) -> RouteDecision | None:
    normalized = " ".join(raw_text.split())
    lowered = normalized.lower()

    negative_hints = (
        "不需要检索",
        "无需检索",
        "不触发检索",
        "不要触发检索",
        "通用对话",
        "branch_0",
        "日常闲聊",
        "信息不足",
    )
    positive_hints = (
        "需要检索",
        "应检索",
        "建议检索",
        "触发检索",
        "走专业咨询",
        "专业咨询",
        "需要专业资料",
        "需要专业知识",
    )

    has_negative = any(hint in normalized or hint in lowered for hint in negative_hints)
    has_positive = any(hint in normalized or hint in lowered for hint in positive_hints)

    decision_snippet = ""
    match = re.search(r"(?:路由决策|结论|最终判断)(?:为|是|:)\s*([^。；\n]+)", normalized)
    if match:
        decision_snippet = match.group(1).strip()
        snippet_lowered = decision_snippet.lower()
        has_negative = has_negative or any(
            hint in decision_snippet or hint in snippet_lowered for hint in negative_hints
        )
        has_positive = has_positive or any(
            hint in decision_snippet or hint in snippet_lowered for hint in positive_hints
        )

    if has_positive and not has_negative:
        return RouteDecision(
            need_retrieval=True,
            reason=_clip_reason(decision_snippet, "关键词判定:需要检索"),
        )
    if has_negative and not has_positive:
        return RouteDecision(
            need_retrieval=False,
            reason=_clip_reason(decision_snippet, "关键词判定:无需检索"),
        )
    return None


def _try_parse_decision_from_text(raw_text: str) -> RouteDecision | None:
    candidates = _build_parse_candidates(raw_text)

    for candidate in candidates:
        try:
            parsed = RouteDecision.model_validate_json(candidate)
            return _sanitize_decision(parsed, DEFAULT_NON_RETRIEVAL_REASON)
        except Exception:
            pass
        try:
            payload = json.loads(candidate)
            parsed = RouteDecision.model_validate(payload)
            return _sanitize_decision(parsed, DEFAULT_NON_RETRIEVAL_REASON)
        except Exception:
            pass

    return _parse_decision_from_keywords(raw_text)



def _coerce_route_decision(route_result: Any, session_id: str = "") -> RouteDecision:
    if isinstance(route_result, RouteDecision):
        return _sanitize_decision(route_result, DEFAULT_NON_RETRIEVAL_REASON)

    if isinstance(route_result, dict):
        parsed = route_result.get("parsed")
        if isinstance(parsed, RouteDecision):
            return _sanitize_decision(parsed, DEFAULT_NON_RETRIEVAL_REASON)
        if isinstance(parsed, dict):
            decision = RouteDecision.model_validate(parsed)
            return _sanitize_decision(decision, DEFAULT_NON_RETRIEVAL_REASON)

        raw = route_result.get("raw")
        if raw is not None:
            raw_content = raw.content if hasattr(raw, "content") else raw
            raw_text = _content_to_text(raw_content)
            if raw_text.strip():
                decision = _try_parse_decision_from_text(raw_text)
                if decision is not None:
                    return decision
                logger.warning(
                    "node=route stage=raw_parse_failed session_id=%s preview=%s",
                    session_id,
                    _preview(raw_text),
                )
            logger.warning(
                "node=route stage=parse_empty_raw session_id=%s raw_type=%s raw_content_type=%s",
                session_id,
                type(raw).__name__,
                type(raw_content).__name__,
            )

        parsing_error = route_result.get("parsing_error")
        if parsing_error is not None:
            raise RuntimeError(f"route structured parse failed: {parsing_error}") from parsing_error
        raise RuntimeError("route structured parse failed: missing parsed/raw payload")

    if hasattr(route_result, "content"):
        raw_text = _content_to_text(route_result.content)
        if raw_text.strip():
            decision = _try_parse_decision_from_text(raw_text)
            if decision is not None:
                return decision
            raise RuntimeError(
                f"failed to parse RouteDecision from plain route output. preview={_preview(raw_text)!r}"
            )

    raise RuntimeError(f"unsupported route result type: {type(route_result)!r}")


def _try_plain_invoke_decision(messages: list[tuple[str, str]], session_id: str) -> RouteDecision | None:
    try:
        raw_result = get_route_llm().invoke(messages)
    except Exception as exc:
        logger.warning(
            "node=route stage=plain_invoke_failed session_id=%s err_type=%s err=%s",
            session_id,
            type(exc).__name__,
            exc,
        )
        return None

    raw_content = raw_result.content if hasattr(raw_result, "content") else raw_result
    raw_text = _content_to_text(raw_content)
    if not raw_text.strip():
        logger.warning("node=route stage=plain_empty_output session_id=%s", session_id)
        return None

    decision = _try_parse_decision_from_text(raw_text)
    if decision is not None:
        return decision

    logger.warning(
        "node=route stage=plain_parse_failed session_id=%s preview=%s",
        session_id,
        _preview(raw_text),
    )
    return None


def route_node(state: GraphState) -> dict:
    start = perf_counter()
    session_id = state.get("session_id", "")
    logger.info("node=route stage=start session_id=%s", session_id)

    messages = [
        ("system", ROUTE_SYSTEM_PROMPT),
        ("user", state["user_message"]),
    ]
    decision = _default_non_retrieval_decision()

    try:
        route_result = _get_route_chain().invoke(messages)
        decision = _coerce_route_decision(route_result, session_id=session_id)
    except Exception as exc:
        logger.warning(
            "node=route stage=structured_invoke_failed session_id=%s err_type=%s err=%s",
            session_id,
            type(exc).__name__,
            exc,
        )
        fallback_decision = _try_plain_invoke_decision(messages, session_id=session_id)
        if fallback_decision is not None:
            decision = fallback_decision
        else:
            logger.warning(
                "node=route stage=default_non_retrieval session_id=%s reason=%s",
                session_id,
                decision.reason,
            )
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(
        "node=route stage=end session_id=%s elapsed_ms=%s need_retrieval=%s reason=%s",
        session_id,
        elapsed_ms,
        decision.need_retrieval,
        decision.reason,
    )
    return {
        "need_retrieval": decision.need_retrieval,
        "route_reason": decision.reason,
    }
