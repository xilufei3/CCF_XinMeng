from typing import TypedDict

from langchain_core.messages import BaseMessage


class GraphState(TypedDict):
    user_message: str
    chat_history: list[BaseMessage]
    session_id: str

    need_retrieval: bool
    route_reason: str | None
    retrieved_docs: list[str]

    final_response: str
    prompt_version: str
