from typing import TypedDict

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
)
from sqlalchemy.ext.asyncio import AsyncSession


class ChatState(TypedDict):
    question: str
    messages: list[ChatCompletionMessageParam]
    iteration_count: int
    tool_call_count: int
    retrieval_count: int
    pending_tool_calls: list[ChatCompletionMessageToolCallUnion]
    answer: str
    stop_reason: str | None


class ChatContext(TypedDict):
    session: AsyncSession
    client: AsyncOpenAI
    model: str
