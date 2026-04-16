import json

from fastapi import HTTPException

from src.app.models.schemas import ChatRequest
from src.app.services.id_utils import build_thread_id, hash_device_id
from src.app.services.lock_manager import thread_lock_manager
from src.app.services.scene_logic import (
    MODEL_UNAVAILABLE_MESSAGE,
    stream_reply,
)
from src.app.services.storage import Storage


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


def _extract_recent_history_rows(rows: list[dict], max_rounds: int) -> list[dict[str, str]]:
    if max_rounds <= 0:
        return []

    normalized: list[dict[str, str]] = []
    for row in rows:
        role = str(row.get("role", "")).strip().lower()
        content = str(row.get("content", "")).strip()
        if role not in {"user", "assistant"}:
            continue
        if not content:
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

    return list(reversed(selected_rev))


async def stream_chat(
    storage: Storage,
    request: ChatRequest,
    device_id_salt: str,
    graph_app=None,
    history_rounds: int = 3,
):
    del graph_app

    device_id_hash = hash_device_id(request.device_id, device_id_salt)
    thread_id = build_thread_id(device_id_hash, request.process_id)

    await storage.upsert_process(thread_id=thread_id, device_id_hash=device_id_hash, process_id=request.process_id)

    async def gen():
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
                await storage.insert_user_processing(thread_id, request.client_msg_id, request.message)
            except Exception as exc:
                raise HTTPException(status_code=409, detail="idempotency conflict") from exc

            history_rows = await storage.load_history(thread_id)
            recent_history = _extract_recent_history_rows(history_rows, max_rounds=history_rounds)

            try:
                assistant_chunks: list[str] = []
                async for piece in stream_reply(
                    request.message,
                    recent_history=recent_history,
                    history_rounds=history_rounds,
                ):
                    if not piece:
                        continue
                    assistant_chunks.append(piece)
                    yield _sse({"thread_id": thread_id, "text": piece})

                assistant_text = "".join(assistant_chunks).strip()
                if not assistant_text:
                    assistant_text = MODEL_UNAVAILABLE_MESSAGE
                    yield _sse({"thread_id": thread_id, "text": assistant_text})

                await storage.insert_assistant_active(
                    thread_id=thread_id,
                    client_msg_id=request.client_msg_id,
                    content=assistant_text,
                    cached=False,
                )
                await storage.mark_user_active(thread_id, request.client_msg_id)

                yield _sse_done()
            except Exception as exc:
                await storage.mark_user_error(thread_id, request.client_msg_id)
                yield _sse({"thread_id": thread_id, "error": str(exc)})
                yield _sse_done()

    return thread_id, gen()
