from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    device_id: str = Field(min_length=1)
    process_id: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    scene: Optional[str] = None
    intent_tag: Optional[str] = None
    created_at: str


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[HistoryMessage]
