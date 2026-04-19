import logging
import os
from typing import Any

from src.app.config import settings

logger = logging.getLogger(__name__)

_langfuse_available = True
_langfuse_import_error: Exception | None = None

try:
    from langfuse import get_client
    from langfuse.langchain import CallbackHandler
except Exception as exc:  # pragma: no cover - depends on optional dependency presence.
    _langfuse_available = False
    _langfuse_import_error = exc
    get_client = None  # type: ignore[assignment]
    CallbackHandler = None  # type: ignore[assignment]

_langfuse_init_attempted = False
_langfuse_enabled = False
_missing_dep_warned = False


def _is_langfuse_configured() -> bool:
    return bool(settings.langfuse_public_key.strip() and settings.langfuse_secret_key.strip())


def init_langfuse() -> bool:
    """Initialize Langfuse client from settings/environment.

    This function is safe to call multiple times.
    """

    global _langfuse_init_attempted
    global _langfuse_enabled
    global _missing_dep_warned

    if _langfuse_init_attempted:
        return _langfuse_enabled
    _langfuse_init_attempted = True

    if not settings.langfuse_enabled:
        logger.info("langfuse disabled: LANGFUSE_ENABLED is false")
        _langfuse_enabled = False
        return False

    if not _is_langfuse_configured():
        logger.info("langfuse disabled: missing LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY")
        _langfuse_enabled = False
        return False

    if not _langfuse_available:
        if not _missing_dep_warned:
            logger.warning(
                "langfuse disabled: dependency not installed err=%s",
                _langfuse_import_error,
            )
            _missing_dep_warned = True
        _langfuse_enabled = False
        return False

    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key.strip())
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key.strip())
    if settings.langfuse_base_url.strip():
        os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url.strip())

    try:
        # Ensure singleton client is initialized early so we fail fast on bad config.
        get_client()
        _langfuse_enabled = True
        logger.info("langfuse enabled base_url=%s", os.environ.get("LANGFUSE_BASE_URL", ""))
        return True
    except Exception as exc:
        logger.warning("langfuse disabled: client init failed err=%s", exc)
        _langfuse_enabled = False
        return False


def is_langfuse_enabled() -> bool:
    if not _langfuse_init_attempted:
        return init_langfuse()
    return _langfuse_enabled


def build_langfuse_runnable_config(
    *,
    session_id: str,
    user_id: str | None = None,
    tags: list[str] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build RunnableConfig payload for LangChain/LangGraph tracing."""
    if not is_langfuse_enabled():
        return None
    try:
        callback = CallbackHandler()
    except Exception as exc:
        logger.warning("langfuse callback creation failed err=%s", exc)
        return None

    metadata: dict[str, Any] = {"langfuse_session_id": session_id}
    if user_id:
        metadata["langfuse_user_id"] = user_id
    if tags:
        metadata["langfuse_tags"] = tags
    if extra_metadata:
        metadata.update(extra_metadata)

    return {
        "callbacks": [callback],
        "metadata": metadata,
    }


def flush_langfuse() -> None:
    if not is_langfuse_enabled():
        return
    try:
        client = get_client()
        shutdown = getattr(client, "shutdown", None)
        if callable(shutdown):
            shutdown()
            return

        flush = getattr(client, "flush", None)
        if callable(flush):
            flush()
    except Exception as exc:
        logger.warning("langfuse flush failed err=%s", exc)
