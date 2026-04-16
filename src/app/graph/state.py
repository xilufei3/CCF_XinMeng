from typing import TypedDict


class GraphState(TypedDict, total=False):
    thread_id: str
    user_message: str
    prompt_version: str
    recent_history: list[dict[str, str]]
    assistant_reply: str
