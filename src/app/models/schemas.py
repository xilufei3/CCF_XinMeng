from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    device_id: str = Field(min_length=1)
    process_id: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[HistoryMessage]
