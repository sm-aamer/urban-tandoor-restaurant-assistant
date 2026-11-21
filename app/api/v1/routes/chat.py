from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import service
from app.chat.llm import OpenRouterConfigurationError
from app.chat.memory import (
    ConversationCapacityError,
    ConversationNotFoundError,
)
from app.core.config import get_settings
from app.dependencies.database import get_session
from app.schemas.chat import ChatHealthResponse, ChatRequest, ChatResponse


class SanitizedChatRoute(APIRoute):
    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def sanitized_route_handler(request: Request) -> Response:
            try:
                return await route_handler(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid chat request.",
                ) from exc

        return sanitized_route_handler


router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    route_class=SanitizedChatRoute,
)
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: SessionDependency,
) -> ChatResponse:
    try:
        result = await service.answer_question(
            session,
            request.question,
            request.conversation_id,
        )
    except OpenRouterConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service is not configured.",
        ) from exc
    except service.ChatProviderError as exc:
        if exc.rate_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Assistant is temporarily rate-limited. Please try again later.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant provider is temporarily unavailable.",
        ) from exc
    except (service.ChatDatabaseError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Restaurant data is temporarily unavailable.",
        ) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Conversation was not found or has expired.",
        ) from exc
    except ConversationCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation service is temporarily at capacity.",
        ) from exc

    success = result.stop_reason == "completed" and result.retrieval_count > 0
    response_status = (
        "completed"
        if success
        else "limited"
        if result.stop_reason == "limit_reached"
        else "unavailable"
    )
    return ChatResponse(
        answer=result.answer,
        success=success,
        status=response_status,
        retrieval_count=result.retrieval_count,
        conversation_id=result.conversation_id,
    )


@router.get("/health", response_model=ChatHealthResponse)
def chat_health() -> ChatHealthResponse:
    api_key = get_settings().openrouter_api_key
    configured = (
        api_key is not None and bool(api_key.get_secret_value().strip())
    )
    return ChatHealthResponse(
        status="ready" if configured else "not_configured",
        openrouter_configured=configured,
    )
