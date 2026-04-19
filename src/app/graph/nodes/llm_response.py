import json
import logging
import os
from time import perf_counter
from typing import Any

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.app.config import settings
from src.app.graph.state import GraphState
from src.app.prompts.report import REPORT_INTERPRETATION_PROMPT, format_report_text_for_prompt
from src.app.prompts.response import (
    RESPONSE_SYSTEM_PROMPT,
    RESPONSE_USER_PROMPT,
    WEB_SEARCH_FORCE_FINAL_ANSWER_PROMPT,
    WEB_SEARCH_UNAVAILABLE_FALLBACK_PROMPT,
)
from src.app.services.llm import get_response_llm

logger = logging.getLogger(__name__)

_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        MessagesPlaceholder("chat_history"),
        ("user", RESPONSE_USER_PROMPT),
    ]
)

_plain_response_llm = None
_tool_enabled_response_llm = None
_web_search_tool = None
_web_search_tool_unavailable = False


def _get_plain_response_llm():
    global _plain_response_llm
    if _plain_response_llm is None:
        _plain_response_llm = get_response_llm()
    return _plain_response_llm


def _get_web_search_tool() -> TavilySearchResults | None:
    global _web_search_tool
    global _web_search_tool_unavailable

    if _web_search_tool_unavailable:
        return None
    if _web_search_tool is not None:
        return _web_search_tool

    if settings.tavily_api_key.strip():
        os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key.strip())

    try:
        _web_search_tool = TavilySearchResults(
            max_results=max(1, int(settings.web_search_tavily_max_results)),
        )
    except Exception as exc:
        _web_search_tool_unavailable = True
        logger.warning("web_search tool init failed; fallback to no-tool mode err=%s", exc)
        return None
    return _web_search_tool


def _get_tool_enabled_response_llm():
    global _tool_enabled_response_llm
    if _tool_enabled_response_llm is not None:
        return _tool_enabled_response_llm

    tool = _get_web_search_tool()
    if tool is None:
        return _get_plain_response_llm()

    try:
        _tool_enabled_response_llm = _get_plain_response_llm().bind_tools([tool])
    except Exception as exc:
        logger.warning("bind_tools failed; fallback to no-tool mode err=%s", exc)
        return _get_plain_response_llm()
    return _tool_enabled_response_llm


def _format_docs(docs: list[str]) -> str:
    if not docs:
        return "(本轮未检索知识库, 请基于通用知识回答)"
    return "\n\n".join(f"[资料{i + 1}]\n{doc}" for i, doc in enumerate(docs))


def build_system_prompt(report_text: str | None) -> str:
    normalized_report_text = str(report_text or "").strip()
    if not normalized_report_text:
        return RESPONSE_SYSTEM_PROMPT

    report_block = f"{format_report_text_for_prompt(normalized_report_text)}\n\n{REPORT_INTERPRETATION_PROMPT}\n"
    marker = "\n# 参考资料\n"

    if marker in RESPONSE_SYSTEM_PROMPT:
        return RESPONSE_SYSTEM_PROMPT.replace(marker, f"\n{report_block}\n# 参考资料\n", 1)
    return f"{RESPONSE_SYSTEM_PROMPT}\n\n{report_block}"


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _extract_tool_calls(message: AIMessage) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list):
        normalized: list[dict[str, Any]] = []
        for idx, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                continue
            tool_name = str(tool_call.get("name") or "").strip()
            if not tool_name:
                continue
            tool_id = str(tool_call.get("id") or f"tool-call-{idx}")
            tool_args = tool_call.get("args", {})
            if not isinstance(tool_args, dict):
                tool_args = {}
            normalized.append({"id": tool_id, "name": tool_name, "args": tool_args})
        return normalized

    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict):
        return []
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return []

    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_tool_calls):
        if not isinstance(raw, dict):
            continue
        function_obj = raw.get("function")
        if not isinstance(function_obj, dict):
            continue
        tool_name = str(function_obj.get("name") or "").strip()
        if not tool_name:
            continue
        tool_id = str(raw.get("id") or f"tool-call-{idx}")
        raw_args = function_obj.get("arguments")
        args_payload: dict[str, Any] = {}
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    args_payload = parsed
            except Exception:
                args_payload = {"query": raw_args}
        elif isinstance(raw_args, dict):
            args_payload = raw_args
        normalized.append({"id": tool_id, "name": tool_name, "args": args_payload})
    return normalized


def _tool_result_to_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        # Keep tool payload compact and predictable for second-pass generation.
        compact_items = result[:8]
        return json.dumps(compact_items, ensure_ascii=False)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def _build_prompt_messages(state: GraphState, docs_text: str) -> list[BaseMessage]:
    return _prompt.format_messages(
        system_prompt=build_system_prompt(state.get("report_text")),
        retrieved_docs=docs_text,
        chat_history=state.get("chat_history", []),
        user_message=state["user_message"],
    )


def _invoke_with_optional_web_search(state: GraphState, docs_text: str) -> AIMessage:
    base_messages = _build_prompt_messages(state, docs_text)
    if not bool(state.get("web_search_enabled")):
        return _get_plain_response_llm().invoke(base_messages)

    tool = _get_web_search_tool()
    if tool is None:
        # Web-search switch is enabled but tool is unavailable: answer directly.
        fallback_messages = base_messages + [
            HumanMessage(content=WEB_SEARCH_UNAVAILABLE_FALLBACK_PROMPT),
        ]
        return _get_plain_response_llm().invoke(fallback_messages)

    llm = _get_tool_enabled_response_llm()
    messages: list[BaseMessage] = list(base_messages)
    max_iterations = max(0, int(settings.web_search_max_iterations))

    for iteration in range(max_iterations + 1):
        ai_message = llm.invoke(messages)
        tool_calls = _extract_tool_calls(ai_message)
        if not tool_calls:
            return ai_message

        if iteration >= max_iterations:
            # Force a final natural-language answer when loop cap is reached.
            final_messages = messages + [
                ai_message,
                HumanMessage(content=WEB_SEARCH_FORCE_FINAL_ANSWER_PROMPT),
            ]
            return _get_plain_response_llm().invoke(final_messages)

        messages.append(ai_message)
        for tool_call in tool_calls:
            tool_call_id = str(tool_call.get("id") or f"tool-call-{iteration}")
            tool_args = tool_call.get("args", {})
            if not isinstance(tool_args, dict):
                tool_args = {}
            try:
                tool_result = tool.invoke(tool_args)
                tool_text = _tool_result_to_text(tool_result)
            except Exception as exc:
                tool_text = f'{{"error":"web_search_failed","detail":"{str(exc)}"}}'
            messages.append(ToolMessage(content=tool_text, tool_call_id=tool_call_id))

    return _get_plain_response_llm().invoke(messages)


def llm_response_node(state: GraphState) -> dict:
    start = perf_counter()
    session_id = state.get("session_id", "")
    logger.info("node=llm_response stage=start session_id=%s", session_id)

    docs_text = _format_docs(state.get("retrieved_docs", []))
    result = _invoke_with_optional_web_search(state, docs_text)
    final_response = _message_content_to_text(result.content).strip()
    if not final_response:
        raise RuntimeError("llm_response returned empty content")

    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(
        "node=llm_response stage=end session_id=%s elapsed_ms=%s response_len=%s prompt_version=%s web_search_enabled=%s",
        session_id,
        elapsed_ms,
        len(final_response),
        state.get("prompt_version", ""),
        bool(state.get("web_search_enabled")),
    )
    return {"final_response": final_response}
