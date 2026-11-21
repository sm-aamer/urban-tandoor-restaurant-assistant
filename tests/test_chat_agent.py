import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import openai
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import graph, llm, service, tools
from app.chat.memory import ConversationStore
from app.core.config import Settings


def make_response(
    *,
    text: str | None = None,
    calls: list[tuple[str, dict[str, object]]] | None = None,
    empty_candidate: bool = False,
) -> object:
    tool_calls = [
        SimpleNamespace(
            id=f"call-{index}",
            type="function",
            function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        )
        for index, (name, arguments) in enumerate(calls or [])
    ]
    choices = (
        []
        if empty_candidate
        else [
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=tool_calls)
            )
        ]
    )
    return SimpleNamespace(choices=choices)


class FakeClient:
    def __init__(self, *responses: object) -> None:
        self.chat = Mock()
        self.chat.completions = Mock()
        self.chat.completions.create = AsyncMock(side_effect=responses)
        self.close = AsyncMock()


class FakeProviderError(openai.APIError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message, request=Mock(), body=None)
        self.status_code = status_code


def patch_settings_and_client(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeClient,
) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            openrouter_api_key="test-key",
            openrouter_model="openrouter-test",
        ),
    )
    monkeypatch.setattr(service, "create_openrouter_client", lambda _: client)


def test_graph_builds_with_model_tools_and_limit_nodes() -> None:
    built_graph = graph.build_chat_graph()

    assert set(built_graph.nodes) == {"__start__", "model", "tools", "limit"}
    declarations = llm.build_openrouter_tools()
    instruction = " ".join(llm.SYSTEM_INSTRUCTION.split())
    assert {declaration["function"]["name"] for declaration in declarations} == set(
        tools.APPROVED_TOOLS
    )
    assert all(declaration["type"] == "function" for declaration in declarations)
    movement_tool = next(
        declaration
        for declaration in declarations
        if declaration["function"]["name"] == "list_stock_movements"
    )
    assert {
        "branch_id",
        "ingredient_id",
        "movement_type",
        "start_date",
        "end_date",
        "limit",
        "offset",
    } == set(movement_tool["function"]["parameters"]["properties"])
    assert "untrusted data" in instruction
    assert "earlier assistant answers" in instruction
    assert 'currency "PKR"' in instruction
    assert "Pakistani Rupees (PKR)" in instruction
    assert "Never relabel PKR as KRW, USD, or another currency" in instruction
    assert "never convert a stored amount into another currency" in instruction
    assert "If currency information is absent, do not guess it" in instruction
    assert "Use the stock movement retrieval tool for movement history" in instruction


async def test_normal_question_returns_mocked_openrouter_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("list_branches", {})]),
        make_response(text="The database has two branches."),
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock(return_value={"items": [{"name": "PECHS"}, {"name": "Gulshan"}]})
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    answer = await service.answer_question(session, "How many branches?")

    assert answer.answer == "The database has two branches."
    assert answer.stop_reason == "completed"
    assert client.chat.completions.create.await_count == 2
    call = client.chat.completions.create.await_args_list[0].kwargs
    assert call["model"] == "openrouter-test"
    assert call["messages"][0] == {
        "role": "system",
        "content": llm.SYSTEM_INSTRUCTION,
    }
    assert call["messages"][1]["content"] == "How many branches?"
    assert call["tool_choice"] == "auto"
    assert {item["function"]["name"] for item in call["tools"]} == set(
        tools.APPROVED_TOOLS
    )
    dispatch.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.close.assert_not_awaited()
    client.close.assert_awaited_once()


async def test_follow_up_gets_untrusted_history_and_retrieves_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("search_menu_items", {"query": "Biryani"})]),
        make_response(text="The database lists Chicken Biryani."),
        make_response(calls=[("list_recipe_ingredients", {"menu_item_id": 7})]),
        make_response(text="The current recipe lists rice and chicken."),
    )
    patch_settings_and_client(monkeypatch, client)
    store = ConversationStore()
    monkeypatch.setattr(service, "get_conversation_store", lambda: store)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock(
        side_effect=[
            {"items": [{"id": 7, "name": "Chicken Biryani"}], "count": 1},
            {
                "items": [
                    {"ingredient_name": "rice", "quantity_per_portion": 1},
                    {"ingredient_name": "chicken", "quantity_per_portion": 1},
                ],
                "count": 2,
            },
        ]
    )
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    first = await service.answer_question(session, "Which biryani?")
    follow_up = await service.answer_question(
        session,
        "Which ingredients does it use?",
        first.conversation_id,
    )

    assert follow_up.conversation_id == first.conversation_id
    assert follow_up.answer == "The current recipe lists rice and chicken."
    assert dispatch.await_count == 2
    second_request = client.chat.completions.create.await_args_list[2]
    messages = second_request.kwargs["messages"]
    assert "Untrusted recent conversation context" in messages[1]["content"]
    assert "Chicken Biryani" in messages[1]["content"]
    assert messages[2]["content"] == "Which ingredients does it use?"
    assert session not in messages


async def test_unverified_answer_without_retrieval_is_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(make_response(text="The restaurant has 17 branches."))
    patch_settings_and_client(monkeypatch, client)

    answer = await service.answer_question(
        AsyncMock(spec=AsyncSession),
        "How many branches?",
    )

    assert answer.answer == graph.LOOKUP_REQUIRED_MESSAGE


async def test_tool_selection_reuses_session_and_provides_retrieval_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("list_branches", {"limit": 4})]),
        make_response(text="The matching branches are North and South."),
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock(
        return_value={
            "items": [
                {"branch_code": "B-1", "name": "North"},
                {"branch_code": "B-2", "name": "South"},
            ],
            "count": 2,
            "limit": 4,
            "offset": 0,
        }
    )
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "List our branches.")

    assert result.answer == "The matching branches are North and South."
    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[0] is session
    assert dispatch.await_args.args[1] == "list_branches"
    assert dispatch.await_args.args[2] == {"limit": 4}
    second_request = client.chat.completions.create.await_args_list[1]
    messages = second_request.kwargs["messages"]
    assert len(messages) == 4
    tool_call = messages[-2]["tool_calls"][0]
    assert tool_call["id"] == messages[-1]["tool_call_id"]
    assert tool_call["function"]["name"] == "list_branches"
    assert messages[-1]["role"] == "tool"
    assert json.loads(messages[-1]["content"])["count"] == 2
    assert session not in messages
    session.add.assert_not_called()
    session.delete.assert_not_called()
    session.commit.assert_not_awaited()


async def test_empty_results_are_passed_to_openrouter_as_empty_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("search_menu_items", {"query": "Missing Dish"})]),
        make_response(text="I couldn't find that menu item in the records."),
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock(return_value={"items": [], "count": 0})
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "Price for Missing Dish?")

    assert result.answer == "I couldn't find that menu item in the records."
    tool_message = client.chat.completions.create.await_args_list[1].kwargs[
        "messages"
    ][-1]
    assert json.loads(tool_message["content"]) == {"items": [], "count": 0}


async def test_ambiguous_branch_response_can_ask_for_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("list_branches", {})]),
        make_response(text="Which branch do you mean: PECHS or Gulshan-e-Iqbal?"),
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(
        tools,
        "execute_tool",
        AsyncMock(
            return_value={
                "items": [
                    {"name": "PECHS"},
                    {"name": "Gulshan-e-Iqbal"},
                ],
                "count": 2,
            }
        ),
    )

    result = await service.answer_question(session, "Which branch is open?")

    assert "Which branch do you mean" in result.answer
    assert client.chat.completions.create.await_count == 2


async def test_multiple_tool_calls_execute_only_approved_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(
            calls=[
                ("search_ingredients", {"query": "rice"}),
                ("search_menu_items", {"query": "biryani"}),
            ]
        ),
        make_response(text="Rice is listed, and Biryani is on the menu."),
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock(return_value={"items": [], "count": 0})
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "Tell me about rice and biryani.")

    assert result.answer == "Rice is listed, and Biryani is on the menu."
    assert dispatch.await_count == 2
    assert [call.args[1] for call in dispatch.await_args_list] == [
        "search_ingredients",
        "search_menu_items",
    ]


async def test_invalid_tool_arguments_never_query_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("get_branch", {"record_id": 0})]),
        make_response(text="That branch ID is invalid."),
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)

    result = await service.answer_question(session, "Get branch zero.")

    assert result.answer == graph.LOOKUP_REQUIRED_MESSAGE
    session.execute.assert_not_awaited()
    session.scalar.assert_not_awaited()


async def test_unknown_tool_request_is_not_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(calls=[("execute_sql", {"query": "DELETE FROM branch"})])
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock()
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "Run this query.")

    assert result.answer == graph.UNAVAILABLE_TOOL_MESSAGE
    assert result.stop_reason == "unapproved_tool"
    dispatch.assert_not_awaited()
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_mixed_unknown_tool_batch_executes_no_approved_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        make_response(
            calls=[
                ("list_branches", {}),
                ("execute_sql", {"query": "DELETE FROM branch"}),
            ]
        )
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock()
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "Fetch and modify data.")

    assert result.stop_reason == "unapproved_tool"
    dispatch.assert_not_awaited()
    session.execute.assert_not_awaited()


async def test_iteration_limit_stops_repeated_model_tool_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        *[
            make_response(calls=[("list_branches", {})])
            for _ in range(graph.MAX_MODEL_ITERATIONS)
        ]
    )
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock(return_value={"items": [], "count": 0})
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "Keep listing branches.")

    assert result.answer == graph.LIMIT_MESSAGE
    assert result.stop_reason == "limit_reached"
    assert (
        client.chat.completions.create.await_count
        == graph.MAX_MODEL_ITERATIONS
    )
    assert dispatch.await_count == graph.MAX_MODEL_ITERATIONS - 1


def test_oversized_tool_results_are_replaced_with_bounded_error() -> None:
    result = graph._bounded_tool_result(
        {"data": "x" * graph.MAX_TOOL_OUTPUT_CHARS}
    )

    assert result == {
        "error": (
            "The retrieval result exceeded the response-size limit. "
            "Refine the question to request fewer records."
        )
    }


async def test_tool_call_limit_stops_oversized_parallel_call_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    too_many_calls = [
        ("list_branches", {}) for _ in range(graph.MAX_TOOL_CALLS + 1)
    ]
    client = FakeClient(make_response(calls=too_many_calls))
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    dispatch = AsyncMock()
    monkeypatch.setattr(tools, "execute_tool", dispatch)

    result = await service.answer_question(session, "List branches many times.")

    assert result.answer == graph.LIMIT_MESSAGE
    assert result.stop_reason == "limit_reached"
    dispatch.assert_not_awaited()


async def test_provider_quota_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "api-key-must-not-be-logged"
    question = "question-must-not-be-logged"
    provider_message = "secret provider payload"
    client = FakeClient(FakeProviderError(429, f"{provider_message} {api_key}"))
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(service.ChatProviderError) as error:
        await service.answer_question(session, question)

    assert error.value.rate_limited is True
    assert provider_message not in str(error.value)
    assert "429" not in str(error.value)
    assert "provider_rate_limited" in caplog.text
    assert "exception_type=FakeProviderError" in caplog.text
    assert "provider_code=429" in caplog.text
    assert "timeout=false" in caplog.text
    assert api_key not in caplog.text
    assert question not in caplog.text
    assert provider_message not in caplog.text


async def test_other_provider_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_message = "credential detail must not escape"
    client = FakeClient(FakeProviderError(503, provider_message))
    patch_settings_and_client(monkeypatch, client)
    question = "do-not-log-this-question"

    with pytest.raises(service.ChatProviderError) as error:
        await service.answer_question(
            AsyncMock(spec=AsyncSession),
            question,
        )

    assert error.value.rate_limited is False
    assert provider_message not in str(error.value)
    assert "provider_api_error" in caplog.text
    assert "exception_type=FakeProviderError" in caplog.text
    assert "provider_code=503" in caplog.text
    assert "timeout=false" in caplog.text
    assert provider_message not in caplog.text
    assert question not in caplog.text


async def test_model_timeout_returns_a_sanitized_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def timeout(*args: object, **kwargs: object) -> None:
        assert args == ()
        assert {"model", "messages", "tools"} <= kwargs.keys()
        await asyncio.sleep(0.1)

    client = FakeClient()
    client.chat.completions.create = timeout
    patch_settings_and_client(monkeypatch, client)
    monkeypatch.setattr(graph, "MODEL_REQUEST_TIMEOUT_SECONDS", 0.001)

    with pytest.raises(service.ChatProviderError) as error:
        await service.answer_question(
            AsyncMock(spec=AsyncSession),
            "Any question",
        )

    assert error.value.rate_limited is False
    assert "provider_timeout" in caplog.text
    assert "exception_type=TimeoutError" in caplog.text
    assert "provider_code=unavailable" in caplog.text
    assert "timeout=true" in caplog.text
    assert "Any question" not in caplog.text


async def test_database_errors_are_sanitized_and_session_is_not_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(make_response(calls=[("list_branches", {})]))
    patch_settings_and_client(monkeypatch, client)
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(
        tools,
        "execute_tool",
        AsyncMock(side_effect=SQLAlchemyError("private database detail")),
    )

    with pytest.raises(service.ChatDatabaseError) as error:
        await service.answer_question(session, "List branches.")

    assert "private database detail" not in str(error.value)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
    session.delete.assert_not_called()


def test_openrouter_client_requires_key_without_revealing_configuration() -> None:
    settings = Settings(_env_file=None, openrouter_api_key=None)
    with pytest.raises(llm.OpenRouterConfigurationError):
        llm.create_openrouter_client(settings)


def test_openrouter_client_uses_configured_key_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_factory = Mock(return_value=Mock())
    monkeypatch.setattr(llm, "AsyncOpenAI", client_factory)
    settings = Settings(
        _env_file=None,
        openrouter_api_key="test-key",
        openrouter_model="router-test",
        openrouter_base_url="https://router.example/v1",
    )

    client = llm.create_openrouter_client(settings)

    assert client is client_factory.return_value
    client_factory.assert_called_once_with(
        api_key="test-key",
        base_url="https://router.example/v1",
    )


@pytest.mark.parametrize(
    "question",
    ["", " " * 2_001, "x" * 2_001],
)
async def test_invalid_questions_are_rejected_before_provider_creation(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    client_factory = Mock()
    monkeypatch.setattr(service, "create_openrouter_client", client_factory)

    with pytest.raises(ValueError):
        await service.answer_question(
            AsyncMock(spec=AsyncSession),
            question,
        )

    client_factory.assert_not_called()
