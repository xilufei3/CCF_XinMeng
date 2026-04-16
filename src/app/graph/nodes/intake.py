import logging
from time import perf_counter

from src.app.graph.state import GraphState
from src.app.prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)


def intake_node(state: GraphState) -> dict:
    start = perf_counter()
    session_id = state.get("session_id", "")
    logger.info("node=intake stage=start session_id=%s", session_id)

    message = state.get("user_message", "").strip()
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
