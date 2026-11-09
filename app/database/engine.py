from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings


class DatabaseConfigurationError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    database_url = get_settings().database_url
    if database_url is None:
        raise DatabaseConfigurationError("DATABASE_URL is not configured.")

    try:
        url = make_url(database_url.get_secret_value())
    except ArgumentError as exc:
        raise DatabaseConfigurationError("DATABASE_URL is invalid.") from exc

    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    elif url.drivername != "postgresql+asyncpg":
        raise DatabaseConfigurationError(
            "DATABASE_URL must use PostgreSQL with the asyncpg driver."
        )

    query = dict(url.query)
    query.pop("sslmode", None)
    query.pop("channel_binding", None)
    query.pop("ssl", None)
    url = url.set(query=query)

    return create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"ssl": "require"},
    )


async def dispose_engine() -> None:
    from app.database.session import get_session_factory

    get_session_factory.cache_clear()
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
