import logging
from time import perf_counter

from src.app.graph.state import GraphState
from src.app.services.retriever import get_retriever

logger = logging.getLogger(__name__)


def retrieve_node(state: GraphState) -> dict:
    start = perf_counter()
    session_id = state.get("session_id", "")
    logger.info("node=retrieve stage=start session_id=%s", session_id)

    retriever = get_retriever()
    docs = retriever.invoke(state["user_message"])
    docs_text = [doc.page_content for doc in docs]
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(
        "node=retrieve stage=end session_id=%s elapsed_ms=%s docs_count=%s",
        session_id,
        elapsed_ms,
        len(docs_text),
    )
    return {"retrieved_docs": docs_text}
