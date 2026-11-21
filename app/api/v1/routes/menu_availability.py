from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.schemas.menu_availability import (
    MenuAvailabilityCreate,
    MenuAvailabilityListResponse,
    MenuAvailabilityRead,
    MenuAvailabilityUpdate,
)
from app.services import menu_availability as menu_availability_service

router = APIRouter(prefix="/menu-availability", tags=["menu-availability"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=MenuAvailabilityListResponse)
async def list_menu_availability(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    branch_id: Annotated[int | None, Query(ge=1)] = None,
    menu_item_id: Annotated[int | None, Query(ge=1)] = None,
    is_available: Annotated[Literal["true", "false", "null"] | None, Query()] = None,
) -> MenuAvailabilityListResponse:
    available_filter = (
        None
        if is_available in (None, "null")
        else is_available == "true"
    )
    records, total = await menu_availability_service.list_menu_availability(
        session,
        limit=limit,
        offset=offset,
        branch_id=branch_id,
        menu_item_id=menu_item_id,
        is_available=available_filter,
        filter_is_available=is_available is not None,
    )
    return MenuAvailabilityListResponse(
        items=[MenuAvailabilityRead.model_validate(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{availability_id}", response_model=MenuAvailabilityRead)
async def get_menu_availability(
    availability_id: int,
    session: SessionDependency,
) -> MenuAvailabilityRead:
    try:
        record = await menu_availability_service.get_menu_availability(
            session,
            availability_id,
        )
    except menu_availability_service.MenuAvailabilityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu availability record not found.",
        ) from exc
    return MenuAvailabilityRead.model_validate(record)


@router.post(
    "",
    response_model=MenuAvailabilityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_menu_availability(
    availability_in: MenuAvailabilityCreate,
    session: SessionDependency,
) -> MenuAvailabilityRead:
    try:
        record = await menu_availability_service.create_menu_availability(
            session,
            availability_in,
        )
    except menu_availability_service.BranchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Branch not found.",
        ) from exc
    except menu_availability_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Menu item not found.",
        ) from exc
    except menu_availability_service.MenuAvailabilityConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability already exists for this branch and menu item.",
        ) from exc
    return MenuAvailabilityRead.model_validate(record)


@router.patch("/{availability_id}", response_model=MenuAvailabilityRead)
async def update_menu_availability(
    availability_id: int,
    availability_in: MenuAvailabilityUpdate,
    session: SessionDependency,
) -> MenuAvailabilityRead:
    try:
        record = await menu_availability_service.update_menu_availability(
            session,
            availability_id,
            availability_in,
        )
    except menu_availability_service.MenuAvailabilityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu availability record not found.",
        ) from exc
    except menu_availability_service.BranchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Branch not found.",
        ) from exc
    except menu_availability_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Menu item not found.",
        ) from exc
    except menu_availability_service.MenuAvailabilityConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability already exists for this branch and menu item.",
        ) from exc
    return MenuAvailabilityRead.model_validate(record)


@router.delete(
    "/{availability_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_menu_availability(
    availability_id: int,
    session: SessionDependency,
) -> Response:
    try:
        await menu_availability_service.delete_menu_availability(
            session,
            availability_id,
        )
    except menu_availability_service.MenuAvailabilityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu availability record not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
