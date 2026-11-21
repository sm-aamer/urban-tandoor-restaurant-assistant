from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MenuItem
from app.repositories import menu_item as menu_item_repository
from app.schemas.menu_item import MenuItemCreate, MenuItemUpdate


class MenuItemNotFoundError(Exception):
    pass


class MenuItemConflictError(Exception):
    pass


async def list_menu_items(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
    category: str | None,
) -> tuple[list[MenuItem], int]:
    return await menu_item_repository.list_menu_items(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
        category=category,
    )


async def get_menu_item(
    session: AsyncSession,
    menu_item_id: int,
) -> MenuItem:
    menu_item = await menu_item_repository.get_menu_item(session, menu_item_id)
    if menu_item is None:
        raise MenuItemNotFoundError
    return menu_item


async def create_menu_item(
    session: AsyncSession,
    menu_item_in: MenuItemCreate,
) -> MenuItem:
    try:
        async with session.begin():
            menu_item = MenuItem(**menu_item_in.model_dump())
            await menu_item_repository.create_menu_item(session, menu_item)
    except IntegrityError as exc:
        raise MenuItemConflictError from exc
    return menu_item


async def update_menu_item(
    session: AsyncSession,
    menu_item_id: int,
    menu_item_in: MenuItemUpdate,
) -> MenuItem:
    try:
        async with session.begin():
            menu_item = await menu_item_repository.get_menu_item(
                session,
                menu_item_id,
            )
            if menu_item is None:
                raise MenuItemNotFoundError
            for field, value in menu_item_in.model_dump(exclude_unset=True).items():
                setattr(menu_item, field, value)
            await menu_item_repository.save_menu_item(session, menu_item)
    except IntegrityError as exc:
        raise MenuItemConflictError from exc
    return menu_item


async def deactivate_menu_item(
    session: AsyncSession,
    menu_item_id: int,
) -> None:
    async with session.begin():
        menu_item = await menu_item_repository.get_menu_item(
            session,
            menu_item_id,
        )
        if menu_item is None:
            raise MenuItemNotFoundError
        menu_item.is_active = False
        await menu_item_repository.save_menu_item(session, menu_item)
