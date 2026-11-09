from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import health
from app.core.config import get_settings
from app.database import engine as database_engine
from app.database.engine import DatabaseConfigurationError
from app.dependencies.database import get_session
from app.main import app


class FakeSessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.closed = False

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


def clear_settings_cache() -> None:
    get_settings.cache_clear()
    database_engine.get_engine.cache_clear()


def test_settings_load_database_url_as_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test-user:test-password@localhost/test-database",
    )
    clear_settings_cache()

    try:
        settings = get_settings()

        assert settings.database_url is not None
        assert settings.database_url.get_secret_value().startswith("postgresql://")
        assert "test-password" not in repr(settings)
    finally:
        clear_settings_cache()


def test_engine_uses_asyncpg_and_requires_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test-user:test-password@localhost/test-database"
        "?sslmode=require&channel_binding=require",
    )
    clear_settings_cache()
    create_engine = Mock(return_value=Mock())
    monkeypatch.setattr(database_engine, "create_async_engine", create_engine)

    try:
        database_engine.get_engine()
    finally:
        clear_settings_cache()

    url, options = create_engine.call_args.args[0], create_engine.call_args.kwargs
    assert url.drivername == "postgresql+asyncpg"
    assert "sslmode" not in url.query
    assert "channel_binding" not in url.query
    assert options["connect_args"] == {"ssl": "require"}
    assert options["pool_pre_ping"] is True


async def test_session_dependency_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    context = FakeSessionContext(session)
    monkeypatch.setattr(
        "app.dependencies.database.get_session_factory",
        lambda: lambda: context,
    )

    dependency: AsyncIterator[AsyncSession] = get_session()
    assert await anext(dependency) is session
    await dependency.aclose()

    assert context.closed


async def test_session_dependency_returns_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_configuration_error() -> None:
        raise DatabaseConfigurationError("secret details must not be returned")

    monkeypatch.setattr(
        "app.dependencies.database.get_session_factory",
        raise_configuration_error,
    )
    dependency = get_session()

    with pytest.raises(HTTPException) as error:
        await anext(dependency)

    assert error.value.status_code == 503
    assert error.value.detail == "Database is unavailable."
    assert "secret details" not in error.value.detail


async def request_database_health(
    session: AsyncSession,
) -> httpx.Response:
    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/health/db")
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_database_health_returns_connected_response() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=Mock())

    response = await request_database_health(session)

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected"}
    assert str(session.execute.call_args.args[0]) == "SELECT 1"


async def test_database_health_returns_sanitized_503() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=SQLAlchemyError("secret connection details"),
    )

    response = await request_database_health(session)

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable."}
    assert "secret connection details" not in response.text


async def test_existing_health_endpoint_remains_independent() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_database_health_router_is_registered() -> None:
    assert any(route.path == "/health/db" for route in health.router.routes)
