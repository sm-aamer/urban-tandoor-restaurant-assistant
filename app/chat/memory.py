import asyncio
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal
from uuid import uuid4

CONVERSATION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"(?i)\b(api[\s_-]?key|password|passwd|secret|token|authorization|"
        r"credential|client[_-]?secret|private[_-]?key|connection[_-]?string)"
        r"['\"]?(\s*[:=]\s*)(['\"]?)[^\s,;'\"]+"
    ),
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?://)\S+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b(?:gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]+"),
)


class ConversationError(ValueError):
    pass


class InvalidConversationIdError(ConversationError):
    pass


class ConversationNotFoundError(ConversationError):
    pass


class ConversationCapacityError(ConversationError):
    pass


@dataclass(frozen=True)
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class _Conversation:
    last_access: float
    messages: list[ConversationMessage] = field(default_factory=list)
    turn_lock: threading.Lock = field(default_factory=threading.Lock)
    active_turns: int = 0


class ConversationStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = 1_800,
        max_conversations: int = 1_000,
        max_messages: int = 10,
        max_message_length: int = 2_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive.")
        if max_conversations < 1:
            raise ValueError("max_conversations must be positive.")
        if max_messages < 2:
            raise ValueError("max_messages must be at least two.")
        if max_message_length < 1:
            raise ValueError("max_message_length must be positive.")

        self.ttl_seconds = ttl_seconds
        self.max_conversations = max_conversations
        self.max_messages = max_messages
        self.max_message_length = max_message_length
        self._clock = clock
        self._guard = threading.RLock()
        self._conversations: dict[str, _Conversation] = {}

    @staticmethod
    def validate_conversation_id(conversation_id: str) -> str:
        if not CONVERSATION_ID_PATTERN.fullmatch(conversation_id):
            raise InvalidConversationIdError("Invalid conversation ID.")
        return conversation_id

    def _remove_expired(self, now: float) -> int:
        expired_ids = [
            conversation_id
            for conversation_id, conversation in self._conversations.items()
            if conversation.active_turns == 0
            and now - conversation.last_access >= self.ttl_seconds
        ]
        for conversation_id in expired_ids:
            del self._conversations[conversation_id]
        return len(expired_ids)

    def _make_room(self, now: float) -> None:
        self._remove_expired(now)
        if len(self._conversations) < self.max_conversations:
            return

        inactive = [
            (conversation.last_access, conversation_id)
            for conversation_id, conversation in self._conversations.items()
            if conversation.active_turns == 0
        ]
        if not inactive:
            raise ConversationCapacityError(
                "Conversation memory is temporarily at capacity."
            )
        _, oldest_id = min(inactive)
        del self._conversations[oldest_id]

    @asynccontextmanager
    async def conversation(
        self,
        conversation_id: str | None = None,
    ) -> AsyncIterator[tuple[str, tuple[ConversationMessage, ...]]]:
        now = self._clock()
        with self._guard:
            self._remove_expired(now)
            if conversation_id is None:
                self._make_room(now)
                conversation_id = str(uuid4())
                while conversation_id in self._conversations:
                    conversation_id = str(uuid4())
                conversation = _Conversation(last_access=now)
                self._conversations[conversation_id] = conversation
            else:
                conversation_id = self.validate_conversation_id(conversation_id)
                conversation = self._conversations.get(conversation_id)
                if conversation is None:
                    raise ConversationNotFoundError(
                        "Conversation was not found or has expired."
                    )
            conversation.active_turns += 1

        acquired = False
        try:
            while not conversation.turn_lock.acquire(blocking=False):
                await asyncio.sleep(0.005)
            acquired = True
            with self._guard:
                conversation.last_access = self._clock()
                history = tuple(conversation.messages)
            yield conversation_id, history
        finally:
            if acquired:
                conversation.turn_lock.release()
            with self._guard:
                conversation.active_turns -= 1
                conversation.last_access = self._clock()

    def record_turn(
        self,
        conversation_id: str,
        question: str,
        answer: str,
    ) -> None:
        with self._guard:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.active_turns == 0:
                raise ConversationNotFoundError(
                    "Conversation was not found or has expired."
                )
            conversation.messages.extend(
                (
                    ConversationMessage("user", self._sanitize(question)),
                    ConversationMessage("assistant", self._sanitize(answer)),
                )
            )
            overflow = max(0, len(conversation.messages) - self.max_messages)
            if (
                overflow < len(conversation.messages)
                and conversation.messages[overflow].role == "assistant"
            ):
                overflow += 1
            conversation.messages = conversation.messages[overflow:]
            conversation.last_access = self._clock()

    def _sanitize(self, content: str) -> str:
        sanitized = content[: self.max_message_length]
        for pattern in SENSITIVE_VALUE_PATTERNS:
            sanitized = pattern.sub("[REDACTED]", sanitized)
        return sanitized[: self.max_message_length]

    def cleanup(self) -> int:
        with self._guard:
            return self._remove_expired(self._clock())

    def __len__(self) -> int:
        with self._guard:
            self._remove_expired(self._clock())
            return len(self._conversations)


def create_conversation_store() -> ConversationStore:
    from app.core.config import get_settings

    settings = get_settings()
    return ConversationStore(
        ttl_seconds=settings.chat_memory_ttl_seconds,
        max_conversations=settings.chat_memory_max_conversations,
        max_messages=settings.chat_memory_max_messages,
        max_message_length=settings.chat_memory_max_message_length,
    )


@lru_cache(maxsize=1)
def get_conversation_store() -> ConversationStore:
    return create_conversation_store()
