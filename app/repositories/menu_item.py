from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import MenuItem


async def list_menu_items(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
    category: str | None,
) -> tuple[list[MenuItem], int]:
    filters = []
    if is_active is not None:
        filters.append(MenuItem.is_active == is_active)
    if category is not None:
        filters.append(MenuItem.category == category)

    statement = select(MenuItem).where(*filters).order_by(MenuItem.menu_code)
    result = await session.execute(statement.offset(offset).limit(limit))
    menu_items = list(result.scalars().all())

    count_statement = select(func.count()).select_from(MenuItem).where(*filters)
    total = await session.scalar(count_statement)
    return menu_items, total or 0


async def get_menu_item(
    session: AsyncSession,
    menu_item_id: int,
) -> MenuItem | None:
    return await session.get(MenuItem, menu_item_id)


async def create_menu_item(
    session: AsyncSession,
    menu_item: MenuItem,
) -> MenuItem:
    session.add(menu_item)
    await session.flush()
    return menu_item


async def save_menu_item(
    session: AsyncSession,
    menu_item: MenuItem,
) -> MenuItem:
    await session.flush()
    return menu_item
