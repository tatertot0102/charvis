"""Pydantic request/response schemas for the HTTP API."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="default", max_length=128)


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int


class CaptureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class CaptureResponse(BaseModel):
    id: int
    status: str = "captured"
