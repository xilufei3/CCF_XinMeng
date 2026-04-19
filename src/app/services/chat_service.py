import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.app.graph.workflow import build_graph
from src.app.models.schemas import ChatRequest
from src.app.prompts import PROMPT_VERSION
from src.app.services.id_utils import build_thread_id, hash_device_id
from src.app.services.lock_manager import thread_lock_manager
from src.app.services.report_session import (
    REPORT_AUTO_TRIGGER_MESSAGE,
    REPORT_SESSION_TYPE,
    is_hidden_client_msg_id,
    load_report_text,
    parse_report_init_command,
)
from src.app.services.storage import Storage

logger = logging.getLogger(__name__)
_STREAM_EVENT_NAMES = {"on_chat_model_stream", "on_llm_stream"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


def _extract_recent_chat_history(rows: list[dict], max_rounds: int) -> list[BaseMessage]:
    if max_rounds <= 0:
        return []

    normalized: list[dict[str, str]] = []
    for row in rows:
        role = str(row.get("role", "")).strip().lower()
        client_msg_id = str(row.get("client_msg_id", "")).strip()
        content = str(row.get("content", "")).strip()
        if role not in {"user", "assistant"}:
            continue
        if not content:
            continue
        if role == "user" and is_hidden_client_msg_id(client_msg_id):
            continue
        normalized.append({"role": role, "content": content})

    if not normalized:
        return []

    selected_rev: list[dict[str, str]] = []
    user_turns = 0
    for item in reversed(normalized):
        selected_rev.append(item)
        if item["role"] == "user":
            user_turns += 1
            if user_turns >= max_rounds:
                break

    selected = list(reversed(selected_rev))
    messages: list[BaseMessage] = []
    for item in selected:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        else:
            messages.append(AIMessage(content=item["content"]))
    return messages


def _extract_text_from_chunk_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "".join(chunks)
    return ""


def _looks_like_llm_response_node(metadata: dict[str, Any]) -> bool:
    node_hints: list[str] = []
    for key in ("langgraph_node", "node_name", "langgraph_path"):
        value = metadata.get(key)
        if isinstance(value, str):
            node_hints.append(value)
        elif isinstance(value, (list, tuple)):
            node_hints.extend(item for item in value if isinstance(item, str))

    if not node_hints:
        # Some library versions omit node hints on stream events.
        # In this case we accept the event to keep streaming compatible.
        return True

    return any("llm_response" in hint for hint in node_hints)


async def _stream_graph_response(
    *,
    graph_app,
    user_message: str,
    session_id: str,
    chat_history: list[BaseMessage],
    session_type: str,
    report_text: str | None,
):
    initial_state = {
        "user_message": user_message,
        "chat_history": chat_history,
        "session_id": session_id,
        "session_type": session_type,
        "report_text": report_text,
        "need_retrieval": False,
        "route_reason": None,
        "retrieved_docs": [],
        "final_response": "",
        "prompt_version": PROMPT_VERSION,
    }

    buffered_final_response = ""

    async for event in graph_app.astream_events(initial_state, version="v2"):
        metadata = event.get("metadata") or {}
        event_name = event.get("event")

        if event_name in _STREAM_EVENT_NAMES and _looks_like_llm_response_node(metadata):
            data = event.get("data") or {}
            chunk = data.get("chunk")
            if chunk is None:
                continue
            chunk_text = _extract_text_from_chunk_content(getattr(chunk, "content", ""))
            if chunk_text:
                yield ("token", chunk_text)

        if event_name == "on_chain_end":
            output = (event.get("data") or {}).get("output")
            if isinstance(output, dict) and "final_response" in output:
                buffered_final_response = str(output.get("final_response", "") or "")

    yield ("final", buffered_final_response)


async def stream_chat(
    storage: Storage,
    request: ChatRequest,
    device_id_salt: str,
    graph_app=None,
    history_rounds: int = 5,
):
    report_init_id = parse_report_init_command(request.message)
    report_text = load_report_text(report_init_id) if report_init_id else None
    if report_init_id and report_text is None:
        raise RuntimeError(f"report not found: {report_init_id}")

    outgoing_user_message = REPORT_AUTO_TRIGGER_MESSAGE if report_init_id else request.message

    device_id_hash = hash_device_id(request.device_id, device_id_salt)
    thread_id = build_thread_id(device_id_hash, request.process_id)

    await storage.upsert_process(
        thread_id=thread_id,
        device_id_hash=device_id_hash,
        process_id=request.process_id,
        session_type=REPORT_SESSION_TYPE if report_init_id else None,
        report_id=report_init_id,
        report_text=report_text,
    )

    if graph_app is None:
        graph_app = build_graph()

    async def gen():
        inserted_processing = False
        try:
            async with thread_lock_manager.lock(thread_id):
                cached_text = await storage.find_cached_assistant(thread_id, request.client_msg_id)
                if cached_text is not None:
                    yield _sse({"thread_id": thread_id, "cached": True, "text": cached_text})
                    yield _sse_done()
                    return

                if await storage.has_processing_user(thread_id, request.client_msg_id):
                    yield _sse({"thread_id": thread_id, "status": "processing", "code": 202})
                    yield _sse_done()
                    return

                try:
                    await storage.insert_user_processing(
                        thread_id,
                        request.client_msg_id,
                        outgoing_user_message,
                    )
                    inserted_processing = True
                except Exception as exc:
                    logger.warning(
                        "stream_chat idempotency conflict thread_id=%s client_msg_id=%s err=%s",
                        thread_id,
                        request.client_msg_id,
                        exc,
                    )
                    yield _sse({"thread_id": thread_id, "error": "idempotency conflict", "code": 409})
                    yield _sse_done()
                    return

                history_rows = await storage.load_history(thread_id)
                chat_history = _extract_recent_chat_history(history_rows, max_rounds=history_rounds)
                process_context = await storage.get_process_context(thread_id)

                assistant_chunks: list[str] = []
                buffered_final_response = ""

                async for kind, payload in _stream_graph_response(
                    graph_app=graph_app,
                    user_message=outgoing_user_message,
                    session_id=thread_id,
                    chat_history=chat_history,
                    session_type=str(process_context.get("session_type") or ""),
                    report_text=process_context.get("report_text"),
                ):
                    if kind == "token":
                        assistant_chunks.append(payload)
                        yield _sse({"thread_id": thread_id, "text": payload})
                    elif kind == "final":
                        buffered_final_response = payload

                assistant_text = "".join(assistant_chunks).strip()
                if not assistant_text and buffered_final_response.strip():
                    assistant_text = buffered_final_response.strip()
                    yield _sse({"thread_id": thread_id, "text": assistant_text})

                if not assistant_text:
                    raise RuntimeError("llm_response returned empty output")

                await storage.insert_assistant_active(
                    thread_id=thread_id,
                    client_msg_id=request.client_msg_id,
                    content=assistant_text,
                    cached=False,
                )
                await storage.mark_user_active(thread_id, request.client_msg_id)

                yield _sse_done()
        except Exception as exc:
            logger.exception("stream_chat failed thread_id=%s err=%s", thread_id, exc)
            if inserted_processing:
                try:
                    await storage.mark_user_error(thread_id, request.client_msg_id)
                except Exception:
                    logger.exception(
                        "stream_chat mark_user_error failed thread_id=%s client_msg_id=%s",
                        thread_id,
                        request.client_msg_id,
                    )
            yield _sse({"thread_id": thread_id, "error": str(exc)})
            yield _sse_done()

    return thread_id, gen()
