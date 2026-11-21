from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes import chat as chat_route
from app.chat.memory import ConversationNotFoundError
from app.core.config import Settings
from app.dependencies.database import get_session
from app.main import app
from app.schemas.chat import ChatRequest, ChatResponse

TEST_CONVERSATION_ID = "d7437f95-112a-4f69-9f31-cf74a4b92ff2"


async def request(
    method: str,
    path: str,
    *,
    session: AsyncSession | None = None,
    json: dict[str, object] | None = None,
) -> httpx.Response:
    fake_session = session or AsyncMock(spec=AsyncSession)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield fake_session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_chat_accepts_valid_question_and_returns_grounded_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = AsyncMock(
        return_value=chat_route.service.ChatResult(
            answer="The database lists two branches.",
            stop_reason="completed",
            retrieval_count=1,
            conversation_id=TEST_CONVERSATION_ID,
        )
    )
    monkeypatch.setattr(chat_route.service, "answer_question", answer)
    session = AsyncMock(spec=AsyncSession)

    response = await request(
        "POST",
        "/api/v1/chat",
        session=session,
        json={"question": "How many branches are there?"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "The database lists two branches.",
        "success": True,
        "status": "completed",
        "retrieval_count": 1,
        "conversation_id": TEST_CONVERSATION_ID,
    }
    answer.assert_awaited_once_with(
        session,
        "How many branches are there?",
        None,
    )
    session.add.assert_not_called()
    session.delete.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "question",
    ["", "   ", "x" * 2_001],
)
async def test_chat_rejects_empty_whitespace_and_oversized_questions(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    answer = AsyncMock()
    monkeypatch.setattr(chat_route.service, "answer_question", answer)

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": question},
    )

    assert response.status_code == 422
    answer.assert_not_awaited()


async def test_chat_rejects_unexpected_or_sensitive_request_fields() -> None:
    response = await request(
        "POST",
        "/api/v1/chat",
        json={
            "question": "List branches.",
            "api_key": "must-not-be-accepted",
            "tool_name": "list_branches",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid chat request."}
    assert "must-not-be-accepted" not in response.text


async def test_chat_accepts_and_returns_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = AsyncMock(
        return_value=chat_route.service.ChatResult(
            answer="It uses chicken and spices.",
            stop_reason="completed",
            retrieval_count=1,
            conversation_id=TEST_CONVERSATION_ID,
        )
    )
    monkeypatch.setattr(chat_route.service, "answer_question", answer)

    response = await request(
        "POST",
        "/api/v1/chat",
        json={
            "question": "Which ingredients does it use?",
            "conversation_id": TEST_CONVERSATION_ID,
        },
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == TEST_CONVERSATION_ID
    answer.assert_awaited_once()
    assert answer.await_args.args[1:] == (
        "Which ingredients does it use?",
        TEST_CONVERSATION_ID,
    )


async def test_chat_rejects_invalid_conversation_id_without_echoing_it() -> None:
    invalid_id = "not-a-conversation-id"
    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "Follow up?", "conversation_id": invalid_id},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid chat request."}
    assert invalid_id not in response.text


async def test_chat_returns_gone_for_expired_or_unknown_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(side_effect=ConversationNotFoundError()),
    )
    response = await request(
        "POST",
        "/api/v1/chat",
        json={
            "question": "Follow up?",
            "conversation_id": TEST_CONVERSATION_ID,
        },
    )

    assert response.status_code == 410
    assert response.json() == {
        "detail": "Conversation was not found or has expired."
    }


async def test_chat_returns_success_false_when_no_retrieval_occurred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(
            return_value=chat_route.service.ChatResult(
                answer="Please ask a question about restaurant records.",
                stop_reason="completed",
                retrieval_count=0,
                conversation_id=TEST_CONVERSATION_ID,
            )
        ),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "Hello."},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["status"] == "unavailable"
    assert response.json()["retrieval_count"] == 0


async def test_chat_reports_iteration_limit_as_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(
            return_value=chat_route.service.ChatResult(
                answer="Please try a narrower question.",
                stop_reason="limit_reached",
                retrieval_count=2,
                conversation_id=TEST_CONVERSATION_ID,
            )
        ),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "List everything."},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["status"] == "limited"


async def test_chat_maps_openrouter_quota_error_to_sanitized_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(
            side_effect=chat_route.service.ChatProviderError(rate_limited=True)
        ),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "List branches."},
    )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "Assistant is temporarily rate-limited. Please try again later."
    }
    assert "API key" not in response.text


async def test_chat_maps_provider_error_to_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(
            side_effect=chat_route.service.ChatProviderError(rate_limited=False)
        ),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "List branches."},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Assistant provider is temporarily unavailable."
    }


async def test_chat_maps_database_error_to_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(
            side_effect=chat_route.service.ChatDatabaseError(
                "private database connection details"
            )
        ),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "List branches."},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Restaurant data is temporarily unavailable."
    }
    assert "private database" not in response.text


async def test_chat_sanitizes_raw_database_error_from_service_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(side_effect=SQLAlchemyError("database password detail")),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "List branches."},
    )

    assert response.status_code == 503
    assert "database password" not in response.text


async def test_chat_maps_missing_openrouter_api_key_to_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route.service,
        "answer_question",
        AsyncMock(side_effect=chat_route.OpenRouterConfigurationError()),
    )

    response = await request(
        "POST",
        "/api/v1/chat",
        json={"question": "List branches."},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Chat service is not configured."}


@pytest.mark.parametrize(
    ("payload", "valid"),
    [
        (
            {
                "answer": "Found one branch.",
                "success": True,
                "status": "completed",
                "retrieval_count": 1,
                "conversation_id": TEST_CONVERSATION_ID,
            },
            True,
        ),
        (
            {
                "answer": "Try again.",
                "success": False,
                "status": "limited",
                "retrieval_count": 0,
                "conversation_id": TEST_CONVERSATION_ID,
            },
            True,
        ),
        (
            {
                "answer": "",
                "success": True,
                "status": "completed",
                "retrieval_count": 1,
                "conversation_id": TEST_CONVERSATION_ID,
            },
            False,
        ),
        (
            {
                "answer": "Found one branch.",
                "success": True,
                "status": "secret",
                "retrieval_count": 1,
                "conversation_id": TEST_CONVERSATION_ID,
            },
            False,
        ),
        (
            {
                "answer": "Found one branch.",
                "success": True,
                "status": "completed",
                "retrieval_count": -1,
                "conversation_id": TEST_CONVERSATION_ID,
            },
            False,
        ),
    ],
)
def test_chat_response_schema_validation(
    payload: dict[str, object],
    valid: bool,
) -> None:
    if valid:
        assert ChatResponse.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            ChatResponse.model_validate(payload)


def test_chat_request_schema_is_strict_and_trims_whitespace() -> None:
    request_model = ChatRequest.model_validate({"question": "  branches?  "})
    assert request_model.question == "branches?"

    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"question": "branches?", "session": "external"})


async def test_chat_health_reports_configuration_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            openrouter_api_key="secret-test-key",
        ),
    )
    response = await request("GET", "/api/v1/chat/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "openrouter_configured": True,
    }
    assert "secret-test-key" not in response.text


async def test_chat_health_reports_missing_key_without_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route,
        "get_settings",
        lambda: Settings(_env_file=None, openrouter_api_key=None),
    )
    response = await request("GET", "/api/v1/chat/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_configured",
        "openrouter_configured": False,
    }


async def test_chat_health_reports_blank_openrouter_key_as_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_route,
        "get_settings",
        lambda: Settings(_env_file=None, openrouter_api_key="   "),
    )
    response = await request("GET", "/api/v1/chat/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_configured",
        "openrouter_configured": False,
    }


def test_openapi_documents_both_chat_endpoints() -> None:
    openapi = FastAPI.openapi(app)
    chat_path = openapi["paths"]["/api/v1/chat"]["post"]
    health_path = openapi["paths"]["/api/v1/chat/health"]["get"]

    assert chat_path["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ] == "#/components/schemas/ChatRequest"
    assert chat_path["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ] == "#/components/schemas/ChatResponse"
    assert health_path["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ] == "#/components/schemas/ChatHealthResponse"


async def test_existing_unversioned_health_endpoint_is_unchanged() -> None:
    response = await request("GET", "/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


async def test_chat_health_does_not_require_database_session() -> None:
    app.dependency_overrides[get_session] = AsyncMock(
        side_effect=AssertionError("health must not request a database session")
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/chat/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
