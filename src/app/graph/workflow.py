from typing import Any

from langgraph.graph import END, START, StateGraph

from src.app.config import settings
from src.app.graph.state import GraphState
from src.app.services.prompts import PROMPT_VERSION
from src.app.services.scene_logic import (
    classify_intent,
    render_scene_reply,
)


def intake_node(state: GraphState) -> GraphState:
    """Start node: normalize inputs and inject prompt metadata."""
    message = state.get("user_message", "").strip()
    return {
        **state,
        "user_message": message,
        "prompt_version": PROMPT_VERSION,
    }


async def intent_node(state: GraphState) -> GraphState:
    """
    Intent-recognition node (architecture-aligned):
    start -> intent -> llm -> ...
    """
    route = await classify_intent(
        state["user_message"],
    )

    return {
        **state,
        "intent": route.intent,
        "scene": route.intent,
    }


async def response_llm_node(state: GraphState) -> GraphState:
    """
    LLM response node (architecture-aligned).
    MVP currently uses deterministic scene prompt rendering,
    but keeps this node shape so we can swap to model invoke later.
    """
    scene = state.get("scene", "knowledge")
    reply = await render_scene_reply(
        scene,
        state["user_message"],
        recent_history=state.get("recent_history", []),
        history_rounds=settings.reply_history_rounds,
    )
    return {**state, "assistant_reply": reply}


def build_graph(checkpointer: Any | None = None):
    graph = StateGraph(GraphState)

    graph.add_node("intake", intake_node)
    graph.add_node("intent", intent_node)
    graph.add_node("llm_response", response_llm_node)

    # Reference architecture:
    # START -> intake -> intent -> llm_response -> END
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "intent")
    graph.add_edge("intent", "llm_response")
    graph.add_edge("llm_response", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
