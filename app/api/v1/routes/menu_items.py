from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.schemas.menu_item import (
    MenuItemCreate,
    MenuItemListResponse,
    MenuItemRead,
    MenuItemUpdate,
)
from app.services import menu_item as menu_item_service

router = APIRouter(prefix="/menu-items", tags=["menu-items"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=MenuItemListResponse)
async def list_menu_items(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    is_active: bool | None = None,
    category: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> MenuItemListResponse:
    menu_items, total = await menu_item_service.list_menu_items(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
        category=category,
    )
    return MenuItemListResponse(
        items=[MenuItemRead.model_validate(menu_item) for menu_item in menu_items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{menu_item_id}", response_model=MenuItemRead)
async def get_menu_item(
    menu_item_id: int,
    session: SessionDependency,
) -> MenuItemRead:
    try:
        menu_item = await menu_item_service.get_menu_item(session, menu_item_id)
    except menu_item_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found.",
        ) from exc
    return MenuItemRead.model_validate(menu_item)


@router.post(
    "",
    response_model=MenuItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_menu_item(
    menu_item_in: MenuItemCreate,
    session: SessionDependency,
) -> MenuItemRead:
    try:
        menu_item = await menu_item_service.create_menu_item(session, menu_item_in)
    except menu_item_service.MenuItemConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A menu item with this menu code already exists.",
        ) from exc
    return MenuItemRead.model_validate(menu_item)


@router.patch("/{menu_item_id}", response_model=MenuItemRead)
async def update_menu_item(
    menu_item_id: int,
    menu_item_in: MenuItemUpdate,
    session: SessionDependency,
) -> MenuItemRead:
    try:
        menu_item = await menu_item_service.update_menu_item(
            session,
            menu_item_id,
            menu_item_in,
        )
    except menu_item_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found.",
        ) from exc
    except menu_item_service.MenuItemConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A menu item with this menu code already exists.",
        ) from exc
    return MenuItemRead.model_validate(menu_item)


@router.delete(
    "/{menu_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_menu_item(
    menu_item_id: int,
    session: SessionDependency,
) -> Response:
    try:
        await menu_item_service.deactivate_menu_item(session, menu_item_id)
    except menu_item_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
