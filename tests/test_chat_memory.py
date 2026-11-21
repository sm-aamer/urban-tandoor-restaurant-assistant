import asyncio

import pytest

from app.chat.memory import (
    ConversationCapacityError,
    ConversationNotFoundError,
    ConversationStore,
    InvalidConversationIdError,
)


async def test_new_conversation_uses_random_valid_id_and_starts_empty() -> None:
    store = ConversationStore()

    async with store.conversation() as (conversation_id, history):
        assert len(conversation_id) == 36
        assert conversation_id[14] == "4"
        assert history == ()
        store.record_turn(conversation_id, "Question", "Answer")


async def test_follow_up_reuses_recent_context() -> None:
    store = ConversationStore()

    async with store.conversation() as (conversation_id, _):
        store.record_turn(conversation_id, "Which dish?", "Chicken Karahi.")

    async with store.conversation(conversation_id) as (reused_id, history):
        assert reused_id == conversation_id
        assert [(message.role, message.content) for message in history] == [
            ("user", "Which dish?"),
            ("assistant", "Chicken Karahi."),
        ]


async def test_conversations_are_isolated() -> None:
    store = ConversationStore()
    async with store.conversation() as (first_id, _):
        store.record_turn(first_id, "First", "First answer")
    async with store.conversation() as (second_id, _):
        store.record_turn(second_id, "Second", "Second answer")

    async with store.conversation(first_id) as (_, first_history):
        assert [message.content for message in first_history] == [
            "First",
            "First answer",
        ]
    async with store.conversation(second_id) as (_, second_history):
        assert [message.content for message in second_history] == [
            "Second",
            "Second answer",
        ]


@pytest.mark.parametrize(
    "conversation_id",
    [
        "invalid",
        "d7437f95-112a-1f69-9f31-cf74a4b92ff2",
        "D7437F95-112A-4F69-9F31-CF74A4B92FF2",
    ],
)
async def test_invalid_conversation_id_is_rejected(conversation_id: str) -> None:
    store = ConversationStore()

    with pytest.raises(InvalidConversationIdError):
        async with store.conversation(conversation_id):
            pass


async def test_unknown_and_expired_conversation_ids_are_not_recreated() -> None:
    now = [0.0]
    store = ConversationStore(ttl_seconds=10, clock=lambda: now[0])

    async with store.conversation() as (conversation_id, _):
        store.record_turn(conversation_id, "Question", "Answer")
    now[0] = 10.0

    assert store.cleanup() == 1
    with pytest.raises(ConversationNotFoundError):
        async with store.conversation(conversation_id):
            pass


async def test_ttl_is_refreshed_by_activity() -> None:
    now = [0.0]
    store = ConversationStore(ttl_seconds=10, clock=lambda: now[0])
    async with store.conversation() as (conversation_id, _):
        store.record_turn(conversation_id, "Question", "Answer")

    now[0] = 9.0
    async with store.conversation(conversation_id):
        pass
    now[0] = 18.0
    assert store.cleanup() == 0
    now[0] = 19.0
    assert store.cleanup() == 1


async def test_message_count_and_length_are_bounded_and_secrets_redacted() -> None:
    store = ConversationStore(max_messages=4, max_message_length=30)
    async with store.conversation() as (conversation_id, _):
        store.record_turn(
            conversation_id,
            "first question",
            "first answer",
        )
        store.record_turn(
            conversation_id,
            "second question API_KEY=never-store-this",
            "second answer",
        )
        store.record_turn(
            conversation_id,
            "third question is longer than the configured maximum",
            "third answer",
        )

    async with store.conversation(conversation_id) as (_, history):
        assert len(history) == 4
        assert [message.role for message in history] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert all(len(message.content) <= 30 for message in history)
        assert "never-store-this" not in repr(history)
        assert history[0].content.startswith("second question")
        assert history[2].content.startswith("third question")


async def test_common_key_and_database_url_formats_are_not_stored() -> None:
    store = ConversationStore()
    gemini_key = "AIza" + ("A" * 30)
    database_url = "postgresql://user:password@db.example.test/service"
    async with store.conversation() as (conversation_id, _):
        store.record_turn(
            conversation_id,
            f'"api_key": "{gemini_key}" {database_url}',
            "Acknowledged.",
        )

    async with store.conversation(conversation_id) as (_, history):
        stored = " ".join(message.content for message in history)
        assert gemini_key not in stored
        assert database_url not in stored


async def test_lru_capacity_evicts_inactive_oldest_conversation() -> None:
    now = [0.0]
    store = ConversationStore(max_conversations=2, clock=lambda: now[0])
    async with store.conversation() as (oldest, _):
        store.record_turn(oldest, "old", "old answer")
    now[0] = 1.0
    async with store.conversation() as (newer, _):
        store.record_turn(newer, "new", "new answer")
    now[0] = 2.0
    async with store.conversation() as (latest, _):
        store.record_turn(latest, "latest", "latest answer")

    with pytest.raises(ConversationNotFoundError):
        async with store.conversation(oldest):
            pass
    async with store.conversation(newer):
        pass
    async with store.conversation(latest):
        pass


async def test_capacity_rejects_new_conversation_when_all_slots_are_active() -> None:
    store = ConversationStore(max_conversations=1)
    async with store.conversation():
        with pytest.raises(ConversationCapacityError):
            async with store.conversation():
                pass


async def test_concurrent_turns_are_serialized_and_receive_updated_history() -> None:
    store = ConversationStore()
    async with store.conversation() as (conversation_id, _):
        store.record_turn(conversation_id, "First", "First answer")

    second_entered = asyncio.Event()
    second_history: list[str] = []

    async def second_turn() -> None:
        async with store.conversation(conversation_id) as (_, history):
            second_history.extend(message.content for message in history)
            second_entered.set()

    async with store.conversation(conversation_id):
        task = asyncio.create_task(second_turn())
        await asyncio.sleep(0.02)
        assert not second_entered.is_set()
        store.record_turn(conversation_id, "Next", "Next answer")

    await asyncio.wait_for(task, timeout=1)
    assert second_history == [
        "First",
        "First answer",
        "Next",
        "Next answer",
    ]
