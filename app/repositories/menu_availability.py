from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Branch, MenuAvailability, MenuItem


async def list_menu_availability(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    branch_id: int | None,
    menu_item_id: int | None,
    is_available: bool | None,
    filter_is_available: bool,
) -> tuple[list[MenuAvailability], int]:
    filters = []
    if branch_id is not None:
        filters.append(MenuAvailability.branch_id == branch_id)
    if menu_item_id is not None:
        filters.append(MenuAvailability.menu_item_id == menu_item_id)
    if filter_is_available:
        filters.append(MenuAvailability.is_available == is_available)

    statement = select(MenuAvailability).where(*filters).order_by(MenuAvailability.id)
    result = await session.execute(statement.offset(offset).limit(limit))
    records = list(result.scalars().all())

    count_statement = (
        select(func.count()).select_from(MenuAvailability).where(*filters)
    )
    total = await session.scalar(count_statement)
    return records, total or 0


async def get_menu_availability(
    session: AsyncSession,
    availability_id: int,
) -> MenuAvailability | None:
    return await session.get(MenuAvailability, availability_id)


async def branch_exists(session: AsyncSession, branch_id: int) -> bool:
    return await session.get(Branch, branch_id) is not None


async def menu_item_exists(session: AsyncSession, menu_item_id: int) -> bool:
    return await session.get(MenuItem, menu_item_id) is not None


async def combination_exists(
    session: AsyncSession,
    branch_id: int,
    menu_item_id: int,
    *,
    exclude_availability_id: int | None = None,
) -> bool:
    statement = select(MenuAvailability.id).where(
        MenuAvailability.branch_id == branch_id,
        MenuAvailability.menu_item_id == menu_item_id,
    )
    if exclude_availability_id is not None:
        statement = statement.where(
            MenuAvailability.id != exclude_availability_id
        )
    return await session.scalar(statement) is not None


async def create_menu_availability(
    session: AsyncSession,
    availability: MenuAvailability,
) -> MenuAvailability:
    session.add(availability)
    await session.flush()
    return availability


async def save_menu_availability(
    session: AsyncSession,
    availability: MenuAvailability,
) -> MenuAvailability:
    await session.flush()
    return availability


async def delete_menu_availability(
    session: AsyncSession,
    availability: MenuAvailability,
) -> None:
    await session.delete(availability)
    await session.flush()
