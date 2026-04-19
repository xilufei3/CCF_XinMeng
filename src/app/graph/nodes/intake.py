import logging
from time import perf_counter

from src.app.graph.state import GraphState
from src.app.prompts import PROMPT_VERSION
from src.app.services.report_session import (
    REPORT_AUTO_TRIGGER_MESSAGE,
    REPORT_SESSION_TYPE,
)

logger = logging.getLogger(__name__)


def intake_node(state: GraphState) -> dict:
    start = perf_counter()
    session_id = state.get("session_id", "")
    logger.info("node=intake stage=start session_id=%s", session_id)

    message = state.get("user_message", "").strip()
    has_history = len(state.get("chat_history", [])) > 0
    if (
        state.get("session_type") == REPORT_SESSION_TYPE
        and state.get("report_text")
        and not has_history
    ):
        message = REPORT_AUTO_TRIGGER_MESSAGE

    result = {
        "user_message": message,
        "prompt_version": PROMPT_VERSION,
    }

    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(
        "node=intake stage=end session_id=%s elapsed_ms=%s prompt_version=%s",
        session_id,
        elapsed_ms,
        PROMPT_VERSION,
    )
    return result
