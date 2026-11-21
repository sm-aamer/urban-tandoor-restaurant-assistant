from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MenuAvailability
from app.repositories import menu_availability as menu_availability_repository
from app.schemas.menu_availability import (
    MenuAvailabilityCreate,
    MenuAvailabilityUpdate,
)


class MenuAvailabilityNotFoundError(Exception):
    pass


class MenuAvailabilityConflictError(Exception):
    pass


class BranchNotFoundError(Exception):
    pass


class MenuItemNotFoundError(Exception):
    pass


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
    return await menu_availability_repository.list_menu_availability(
        session,
        limit=limit,
        offset=offset,
        branch_id=branch_id,
        menu_item_id=menu_item_id,
        is_available=is_available,
        filter_is_available=filter_is_available,
    )


async def get_menu_availability(
    session: AsyncSession,
    availability_id: int,
) -> MenuAvailability:
    record = await menu_availability_repository.get_menu_availability(
        session,
        availability_id,
    )
    if record is None:
        raise MenuAvailabilityNotFoundError
    return record


async def _validate_parents(
    session: AsyncSession,
    branch_id: int,
    menu_item_id: int,
) -> None:
    if not await menu_availability_repository.branch_exists(session, branch_id):
        raise BranchNotFoundError
    if not await menu_availability_repository.menu_item_exists(
        session,
        menu_item_id,
    ):
        raise MenuItemNotFoundError


async def create_menu_availability(
    session: AsyncSession,
    availability_in: MenuAvailabilityCreate,
) -> MenuAvailability:
    try:
        async with session.begin():
            await _validate_parents(
                session,
                availability_in.branch_id,
                availability_in.menu_item_id,
            )
            if await menu_availability_repository.combination_exists(
                session,
                availability_in.branch_id,
                availability_in.menu_item_id,
            ):
                raise MenuAvailabilityConflictError
            availability = MenuAvailability(**availability_in.model_dump())
            await menu_availability_repository.create_menu_availability(
                session,
                availability,
            )
    except IntegrityError as exc:
        raise MenuAvailabilityConflictError from exc
    return availability


async def update_menu_availability(
    session: AsyncSession,
    availability_id: int,
    availability_in: MenuAvailabilityUpdate,
) -> MenuAvailability:
    try:
        async with session.begin():
            availability = await menu_availability_repository.get_menu_availability(
                session,
                availability_id,
            )
            if availability is None:
                raise MenuAvailabilityNotFoundError

            updates = availability_in.model_dump(exclude_unset=True)
            branch_id = updates.get("branch_id", availability.branch_id)
            menu_item_id = updates.get("menu_item_id", availability.menu_item_id)
            if "branch_id" in updates or "menu_item_id" in updates:
                await _validate_parents(session, branch_id, menu_item_id)
                if await menu_availability_repository.combination_exists(
                    session,
                    branch_id,
                    menu_item_id,
                    exclude_availability_id=availability_id,
                ):
                    raise MenuAvailabilityConflictError

            for field, value in updates.items():
                setattr(availability, field, value)
            await menu_availability_repository.save_menu_availability(
                session,
                availability,
            )
    except IntegrityError as exc:
        raise MenuAvailabilityConflictError from exc
    return availability


async def delete_menu_availability(
    session: AsyncSession,
    availability_id: int,
) -> None:
    async with session.begin():
        availability = await menu_availability_repository.get_menu_availability(
            session,
            availability_id,
        )
        if availability is None:
            raise MenuAvailabilityNotFoundError
        await menu_availability_repository.delete_menu_availability(
            session,
            availability,
        )
