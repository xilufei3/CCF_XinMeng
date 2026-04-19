import logging
from time import perf_counter

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.app.graph.state import GraphState
from src.app.prompts.report import REPORT_INTERPRETATION_PROMPT, format_report_text_for_prompt
from src.app.prompts.response import RESPONSE_SYSTEM_PROMPT, RESPONSE_USER_PROMPT
from src.app.services.llm import get_response_llm

logger = logging.getLogger(__name__)

_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        MessagesPlaceholder("chat_history"),
        ("user", RESPONSE_USER_PROMPT),
    ]
)

_response_chain = None


def _get_response_chain():
    global _response_chain
    if _response_chain is None:
        _response_chain = _prompt | get_response_llm()
    return _response_chain


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


def _message_content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def llm_response_node(state: GraphState) -> dict:
    start = perf_counter()
    session_id = state.get("session_id", "")
    logger.info("node=llm_response stage=start session_id=%s", session_id)

    docs_text = _format_docs(state.get("retrieved_docs", []))
    result = _get_response_chain().invoke(
        {
            "system_prompt": build_system_prompt(state.get("report_text")),
            "retrieved_docs": docs_text,
            "chat_history": state.get("chat_history", []),
            "user_message": state["user_message"],
        }
    )
    final_response = _message_content_to_text(result.content).strip()
    if not final_response:
        raise RuntimeError("llm_response returned empty content")

    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(
        "node=llm_response stage=end session_id=%s elapsed_ms=%s response_len=%s prompt_version=%s",
        session_id,
        elapsed_ms,
        len(final_response),
        state.get("prompt_version", ""),
    )
    return {"final_response": final_response}
