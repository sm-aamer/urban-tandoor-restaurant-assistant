from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.chat.memory import CONVERSATION_ID_PATTERN


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    question: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
        pattern=CONVERSATION_ID_PATTERN.pattern,
    )


class ChatResponse(BaseModel):
    answer: str = Field(min_length=1, max_length=2_000)
    success: bool
    status: Literal["completed", "limited", "unavailable"]
    retrieval_count: int = Field(ge=0)
    conversation_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=CONVERSATION_ID_PATTERN.pattern,
    )


class ChatHealthResponse(BaseModel):
    status: Literal["ready", "not_configured"]
    openrouter_configured: bool
