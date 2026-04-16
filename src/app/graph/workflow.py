from typing import Any

from langgraph.graph import END, START, StateGraph

from src.app.config import settings
from src.app.graph.state import GraphState
from src.app.services.prompts import PROMPT_VERSION
from src.app.services.scene_logic import (
    render_reply,
)


def intake_node(state: GraphState) -> GraphState:
    """Start node: normalize inputs and inject prompt metadata."""
    message = state.get("user_message", "").strip()
    return {
        **state,
        "user_message": message,
        "prompt_version": PROMPT_VERSION,
    }


async def response_llm_node(state: GraphState) -> GraphState:
    """LLM response node."""
    reply = await render_reply(
        state["user_message"],
        recent_history=state.get("recent_history", []),
        history_rounds=settings.reply_history_rounds,
    )
    return {**state, "assistant_reply": reply}


def build_graph(checkpointer: Any | None = None):
    graph = StateGraph(GraphState)

    graph.add_node("intake", intake_node)
    graph.add_node("llm_response", response_llm_node)

    # START -> intake -> llm_response -> END
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "llm_response")
    graph.add_edge("llm_response", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
