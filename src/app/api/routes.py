import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.app.models.schemas import ChatRequest, HistoryMessage, HistoryResponse
from src.app.services.chat_service import stream_chat
from src.app.services.id_utils import build_thread_id, hash_device_id

router = APIRouter()

DEVICE_COOKIE_KEY = "dyslexia_device_id"
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year
DEFAULT_ASSISTANT_ID = "agent"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_iso(ts: str | None) -> str:
    if ts:
        return ts
    return _now_iso()


def _safe_json(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        return body
    return {}


async def _read_json(request: Request) -> dict[str, Any]:
    try:
        return _safe_json(await request.json())
    except Exception:
        return {}


def _extract_text_from_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return " ".join(chunks).strip()


def _to_ui_message(role: str, content: str, message_id: str) -> dict[str, Any]:
    role_map = {
        "user": "human",
        "assistant": "ai",
        "system": "system",
        "human": "human",
        "ai": "ai",
    }
    msg_type = role_map.get(role, "human")
    return {"id": message_id, "type": msg_type, "content": content}


def _normalize_history_to_messages(
    process_id: str,
    history_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for idx, item in enumerate(history_rows):
        role = str(item.get("role", "assistant"))
        content = str(item.get("content", ""))
        messages.append(_to_ui_message(role, content, f"{process_id}-m-{idx}"))
    return messages


def _append_pending_human_message(
    base_messages: list[dict[str, Any]],
    *,
    message_id: str,
    content: str,
) -> list[dict[str, Any]]:
    normalized_id = message_id.strip()
    normalized_content = content.strip()
    if not normalized_id or not normalized_content:
        return base_messages

    exists = any(
        isinstance(msg.get("id"), str) and str(msg.get("id")) == normalized_id
        for msg in base_messages
    )
    if exists:
        return base_messages
    return base_messages + [
        {
            "id": normalized_id,
            "type": "human",
            "content": normalized_content,
        }
    ]


def _build_thread_state(
    process_id: str,
    history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    messages = _normalize_history_to_messages(process_id, history_rows)
    checkpoint_id = f"{process_id}-cp-{len(messages)}"
    return {
        "values": {"messages": messages},
        "next": [],
        "checkpoint": {
            "thread_id": process_id,
            "checkpoint_ns": "root",
            "checkpoint_id": checkpoint_id,
            "checkpoint_map": None,
        },
        "metadata": {},
        "created_at": _ensure_iso(history_rows[-1].get("created_at") if history_rows else None),
        "parent_checkpoint": None,
        "tasks": [],
    }


def _build_thread_summary(
    process_id: str,
    assistant_id: str,
    *,
    created_at: str | None = None,
    updated_at: str | None = None,
    values: dict[str, Any] | None = None,
    metadata_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created = _ensure_iso(created_at)
    updated = _ensure_iso(updated_at or created)
    metadata = {
        "assistant_id": assistant_id,
        "graph_id": assistant_id,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return {
        "thread_id": process_id,
        "created_at": created,
        "updated_at": updated,
        "state_updated_at": updated,
        "metadata": metadata,
        "status": "idle",
        "values": values if values is not None else {"messages": []},
        "interrupts": {},
    }


def _normalize_thread_preview(text: Any, limit: int = 80) -> str | None:
    if text is None:
        return None
    normalized = " ".join(str(text).split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _sse_event(event: str, data: Any, event_id: str | None = None) -> str:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _extract_sse_blocks(raw: str) -> tuple[list[str], str]:
    normalized = raw.replace("\r\n", "\n")
    blocks: list[str] = []
    rest = normalized
    while True:
        split_at = rest.find("\n\n")
        if split_at == -1:
            break
        blocks.append(rest[:split_at])
        rest = rest[split_at + 2 :]
    return blocks, rest


def _parse_sse_data_block(block: str) -> str | None:
    lines = [line.rstrip() for line in block.split("\n")]
    data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
    if not data_lines:
        return None
    return "\n".join(data_lines)


def _extract_latest_human_from_input(
    payload_input: Any,
) -> tuple[str, str, list[dict[str, Any]]] | None:
    if not isinstance(payload_input, dict):
        return None
    source = payload_input.get("messages")
    if not isinstance(source, list):
        return None
    all_messages: list[dict[str, Any]] = [
        item for item in source if isinstance(item, dict)
    ]
    for msg in reversed(all_messages):
        role = str(msg.get("type") or msg.get("role") or "").strip().lower()
        if role not in {"human", "user"}:
            continue
        text = _extract_text_from_message_content(msg.get("content"))
        if not text.strip():
            continue
        client_msg_id = str(msg.get("id") or uuid4())
        return text, client_msg_id, all_messages
    return None


def _get_or_create_device_id(request: Request) -> tuple[str, bool]:
    from_cookie = request.cookies.get(DEVICE_COOKIE_KEY)
    if from_cookie and from_cookie.strip():
        return from_cookie, False
    return f"web-{uuid4()}", True


def _apply_device_cookie(response: JSONResponse | StreamingResponse, device_id: str, should_set: bool):
    if not should_set:
        return response
    response.set_cookie(
        key=DEVICE_COOKIE_KEY,
        value=device_id,
        httponly=False,
        max_age=DEVICE_COOKIE_MAX_AGE,
        path="/",
        samesite="lax",
    )
    return response


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    storage = request.app.state.storage
    settings = request.app.state.settings
    graph_app = request.app.state.graph_app

    thread_id, generator = await stream_chat(
        storage=storage,
        request=req,
        device_id_salt=settings.device_id_salt,
        graph_app=graph_app,
        history_rounds=settings.chat_history_rounds,
    )

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Thread-Id": thread_id,
    }
    return StreamingResponse(generator, media_type="text/event-stream", headers=headers)


@router.get("/history", response_model=HistoryResponse)
async def history(
    request: Request,
    device_id: str = Query(min_length=1),
    process_id: str = Query(min_length=1),
):
    storage = request.app.state.storage
    settings = request.app.state.settings

    device_id_hash = hash_device_id(device_id, settings.device_id_salt)
    thread_id = build_thread_id(device_id_hash, process_id)

    rows = await storage.load_history(thread_id)
    messages = [HistoryMessage(**row) for row in rows]
    return HistoryResponse(thread_id=thread_id, messages=messages)


@router.get("/processes")
async def processes(
    request: Request,
    device_id: str = Query(min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    storage = request.app.state.storage
    settings = request.app.state.settings

    device_id_hash = hash_device_id(device_id, settings.device_id_salt)
    items = await storage.list_processes(device_id_hash=device_id_hash, limit=limit, offset=offset)
    return {"items": items}


@router.post("/processes/init")
async def init_process(request: Request, device_id: str, process_id: str):
    storage = request.app.state.storage
    settings = request.app.state.settings

    device_id_hash = hash_device_id(device_id, settings.device_id_salt)
    thread_id = build_thread_id(device_id_hash, process_id)
    await storage.upsert_process(thread_id=thread_id, device_id_hash=device_id_hash, process_id=process_id)
    return {"process_id": process_id, "thread_id": thread_id, "status": "active"}


@router.delete("/processes/{process_id}")
async def delete_process(
    request: Request,
    process_id: str,
    device_id: str = Query(min_length=1),
):
    storage = request.app.state.storage
    settings = request.app.state.settings

    device_id_hash = hash_device_id(device_id, settings.device_id_salt)
    thread_id = build_thread_id(device_id_hash, process_id)
    deleted = await storage.soft_delete_process(thread_id=thread_id, device_id_hash=device_id_hash)
    if not deleted:
        raise HTTPException(status_code=404, detail="process not found")
    return {"process_id": process_id, "thread_id": thread_id, "status": "deleted"}


@router.post("/resume")
async def resume(request: Request, device_id: str, process_id: str):
    # Placeholder endpoint for future checkpoint-based resume control.
    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id_hash = hash_device_id(device_id, settings.device_id_salt)
    thread_id = build_thread_id(device_id_hash, process_id)

    rows = await storage.load_history(thread_id)
    if not rows:
        raise HTTPException(status_code=404, detail="process not found")

    return JSONResponse({"thread_id": thread_id, "status": "resume-ready", "messages": len(rows)})


@router.get("/info")
async def langgraph_info(request: Request):
    device_id, should_set_cookie = _get_or_create_device_id(request)
    response = JSONResponse(
        {
            "name": "dyslexia-ai-mvp-langgraph",
            "version": "0.1.0",
            "transport": "langgraph-compatible-subset",
        }
    )
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.post("/threads")
async def langgraph_create_thread(request: Request):
    body = await _read_json(request)
    process_id_raw = body.get("thread_id")
    process_id = str(process_id_raw).strip() if process_id_raw else str(uuid4())

    metadata = _safe_json(body.get("metadata"))
    assistant_id = str(
        metadata.get("assistant_id")
        or metadata.get("graph_id")
        or DEFAULT_ASSISTANT_ID
    ).strip()

    storage = request.app.state.storage
    settings = request.app.state.settings

    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, process_id)
    await storage.upsert_process(
        thread_id=internal_thread_id,
        device_id_hash=device_hash,
        process_id=process_id,
    )

    response = JSONResponse(
        _build_thread_summary(process_id, assistant_id)
    )
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.post("/threads/search")
async def langgraph_search_threads(request: Request):
    body = await _read_json(request)
    limit = body.get("limit", 100)
    try:
        limit = max(1, min(200, int(limit)))
    except Exception:
        limit = 100

    metadata = _safe_json(body.get("metadata"))
    assistant_id = str(
        metadata.get("assistant_id")
        or metadata.get("graph_id")
        or DEFAULT_ASSISTANT_ID
    ).strip()

    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    items = await storage.list_processes(device_id_hash=device_hash, limit=limit, offset=0)

    threads = [
        _build_thread_summary(
            process_id,
            assistant_id,
            created_at=str(item.get("created_at")) if item.get("created_at") else None,
            updated_at=str(item.get("updated_at")) if item.get("updated_at") else None,
            values=(
                {
                    "messages": [
                        {
                            "id": f"{process_id}-preview",
                            "type": "human",
                            "content": preview,
                        }
                    ]
                }
                if preview
                else {"messages": []}
            ),
            metadata_extra=(
                {"title": preview, "preview": preview}
                if preview
                else None
            ),
        )
        for item in items
        for process_id in [str(item.get("process_id", ""))]
        for preview in [_normalize_thread_preview(item.get("preview"))]
    ]
    response = JSONResponse(threads)
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.get("/threads/{thread_id}")
async def langgraph_get_thread(request: Request, thread_id: str):
    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, thread_id)

    rows = await storage.load_history(internal_thread_id)
    values = {"messages": _normalize_history_to_messages(thread_id, rows)}
    response = JSONResponse(
        _build_thread_summary(
            thread_id,
            DEFAULT_ASSISTANT_ID,
            created_at=str(rows[0].get("created_at")) if rows else None,
            updated_at=str(rows[-1].get("created_at")) if rows else None,
            values=values,
        )
    )
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.delete("/threads/{thread_id}")
async def langgraph_delete_thread(request: Request, thread_id: str):
    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, thread_id)

    deleted = await storage.soft_delete_process(
        thread_id=internal_thread_id,
        device_id_hash=device_hash,
    )
    if not deleted:
        response = JSONResponse(
            {"error": "thread_not_found", "message": f"Thread '{thread_id}' not found"},
            status_code=404,
        )
        return _apply_device_cookie(response, device_id, should_set_cookie)

    response = JSONResponse({"thread_id": thread_id, "status": "deleted"})
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.post("/threads/{thread_id}/history")
async def langgraph_thread_history(request: Request, thread_id: str):
    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, thread_id)

    rows = await storage.load_history(internal_thread_id)
    states = [_build_thread_state(thread_id, rows)] if rows else []
    response = JSONResponse(states)
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.get("/threads/{thread_id}/state")
async def langgraph_thread_state(request: Request, thread_id: str):
    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, thread_id)

    rows = await storage.load_history(internal_thread_id)
    state = _build_thread_state(thread_id, rows)
    response = JSONResponse(state)
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.post("/threads/{thread_id}/runs/stream")
async def langgraph_run_stream(request: Request, thread_id: str):
    storage = request.app.state.storage
    settings = request.app.state.settings
    graph_app = request.app.state.graph_app

    body = await _read_json(request)
    latest = _extract_latest_human_from_input(body.get("input"))

    outgoing_message = latest[0] if latest is not None else ""
    client_msg_id = latest[1] if latest is not None else f"regen-{int(datetime.now().timestamp() * 1000)}"

    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, thread_id)
    rows = await storage.load_history(internal_thread_id)
    base_messages = _normalize_history_to_messages(thread_id, rows)

    if not outgoing_message.strip():
        last_user = next(
            (item for item in reversed(rows) if str(item.get("role", "")).lower() == "user"),
            None,
        )
        if not last_user:
            error_response = JSONResponse(
                {"error": "Cannot infer user input. Submit a human message first."},
                status_code=400,
            )
            return _apply_device_cookie(error_response, device_id, should_set_cookie)
        outgoing_message = str(last_user.get("content", ""))
    else:
        base_messages = _append_pending_human_message(
            base_messages,
            message_id=client_msg_id,
            content=outgoing_message,
        )

    _, backend_stream = await stream_chat(
        storage=storage,
        request=ChatRequest(
            device_id=device_id,
            process_id=thread_id,
            client_msg_id=client_msg_id,
            message=outgoing_message,
        ),
        device_id_salt=settings.device_id_salt,
        graph_app=graph_app,
        history_rounds=settings.chat_history_rounds,
    )

    run_id = str(uuid4())
    ai_message_id = f"{thread_id}-ai-{run_id}"

    async def out_stream():
        event_seq = 0
        assistant_text = ""
        buffer = ""

        def emit_values(messages: list[dict[str, Any]], event_id: str) -> str:
            return _sse_event("values", {"messages": messages}, event_id)

        def emit_error(error: str, message: str, event_id: str) -> str:
            return _sse_event("error", {"error": error, "message": message}, event_id)

        yield emit_values(base_messages, str(event_seq))
        event_seq += 1

        try:
            async for chunk in backend_stream:
                buffer += chunk
                blocks, buffer = _extract_sse_blocks(buffer)
                for block in blocks:
                    data_text = _parse_sse_data_block(block)
                    if not data_text or data_text == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data_text)
                    except Exception:
                        continue

                    if isinstance(payload.get("error"), str):
                        err = str(payload["error"])
                        yield emit_error(err, err, str(event_seq))
                        event_seq += 1
                        continue

                    if payload.get("status") == "processing":
                        yield emit_error(
                            "already_processing",
                            "A response is already being generated for this message. Please retry shortly.",
                            str(event_seq),
                        )
                        event_seq += 1
                        continue

                    text = payload.get("text")
                    if isinstance(text, str):
                        assistant_text += text
                        yield emit_values(
                            base_messages
                            + [
                                {
                                    "id": ai_message_id,
                                    "type": "ai",
                                    "content": assistant_text,
                                }
                            ],
                            str(event_seq),
                        )
                        event_seq += 1

            if buffer.strip():
                data_text = _parse_sse_data_block(buffer)
                if data_text and data_text != "[DONE]":
                    try:
                        payload = json.loads(data_text)
                    except Exception:
                        payload = {}
                    text = payload.get("text")
                    if isinstance(text, str):
                        assistant_text += text
                        yield emit_values(
                            base_messages
                            + [
                                {
                                    "id": ai_message_id,
                                    "type": "ai",
                                    "content": assistant_text,
                                }
                            ],
                            str(event_seq),
                        )
        except Exception as exc:
            yield emit_error("adapter_stream_error", str(exc), str(event_seq))

    response = StreamingResponse(
        out_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "Content-Location": f"/threads/{thread_id}/runs/{run_id}",
            "Location": f"/threads/{thread_id}/runs/{run_id}/stream",
        },
    )
    return _apply_device_cookie(response, device_id, should_set_cookie)


@router.get("/threads/{thread_id}/runs/{run_id}/stream")
async def langgraph_join_run_stream(request: Request, thread_id: str, run_id: str):
    del run_id
    storage = request.app.state.storage
    settings = request.app.state.settings
    device_id, should_set_cookie = _get_or_create_device_id(request)
    device_hash = hash_device_id(device_id, settings.device_id_salt)
    internal_thread_id = build_thread_id(device_hash, thread_id)
    rows = await storage.load_history(internal_thread_id)
    state = _build_thread_state(thread_id, rows)
    payload = _sse_event("values", state.get("values", {}), "0")

    response = StreamingResponse(
        iter([payload]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )
    return _apply_device_cookie(response, device_id, should_set_cookie)
