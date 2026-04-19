from typing import NotRequired, TypedDict

from langchain_core.messages import BaseMessage


class GraphState(TypedDict):
    user_message: str
    chat_history: list[BaseMessage]
    session_id: str
    session_type: NotRequired[str]
    report_text: NotRequired[str | None]

    need_retrieval: bool
    route_reason: str | None
    retrieved_docs: list[str]

    final_response: str
    prompt_version: str
