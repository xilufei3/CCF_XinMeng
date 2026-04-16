from typing import Literal, TypedDict

Scene = Literal["knowledge", "emotion", "advice", "service", "offtopic"]


class GraphState(TypedDict, total=False):
    thread_id: str
    user_message: str
    scene: Scene
    intent: str
    prompt_version: str
    recent_history: list[dict[str, str]]
    assistant_reply: str
