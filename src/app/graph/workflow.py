from typing import Any

from langgraph.graph import END, START, StateGraph

from src.app.graph.nodes.intake import intake_node
from src.app.graph.nodes.llm_response import llm_response_node
from src.app.graph.nodes.retrieve import retrieve_node
from src.app.graph.nodes.route import route_node
from src.app.graph.state import GraphState


def _route_next_node(state: GraphState) -> str:
    return "retrieve" if state["need_retrieval"] else "llm_response"


def build_graph(checkpointer: Any | None = None):
    graph = StateGraph(GraphState)

    graph.add_node("intake", intake_node)
    graph.add_node("route", route_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("llm_response", llm_response_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "route")
    graph.add_conditional_edges(
        "route",
        _route_next_node,
        {
            "retrieve": "retrieve",
            "llm_response": "llm_response",
        },
    )
    graph.add_edge("retrieve", "llm_response")
    graph.add_edge("llm_response", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
