from collections.abc import AsyncIterator

from fastapi import HTTPException
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.engine import DatabaseConfigurationError
from app.database.session import get_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    try:
        session_factory = get_session_factory()
    except (DatabaseConfigurationError, SettingsError, ValidationError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable.",
        ) from exc

    async with session_factory() as session:
        yield session
