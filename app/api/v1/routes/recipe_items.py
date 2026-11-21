from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.schemas.recipe_item import (
    RecipeItemCreate,
    RecipeItemListResponse,
    RecipeItemRead,
    RecipeItemUpdate,
)
from app.services import recipe_item as recipe_item_service

router = APIRouter(prefix="/recipe-items", tags=["recipe-items"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=RecipeItemListResponse)
async def list_recipe_items(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    menu_item_id: Annotated[int | None, Query(ge=1)] = None,
    ingredient_id: Annotated[int | None, Query(ge=1)] = None,
) -> RecipeItemListResponse:
    recipe_items, total = await recipe_item_service.list_recipe_items(
        session,
        limit=limit,
        offset=offset,
        menu_item_id=menu_item_id,
        ingredient_id=ingredient_id,
    )
    return RecipeItemListResponse(
        items=[RecipeItemRead.model_validate(item) for item in recipe_items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{recipe_item_id}", response_model=RecipeItemRead)
async def get_recipe_item(
    recipe_item_id: int,
    session: SessionDependency,
) -> RecipeItemRead:
    try:
        recipe_item = await recipe_item_service.get_recipe_item(
            session,
            recipe_item_id,
        )
    except recipe_item_service.RecipeItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipe item not found.",
        ) from exc
    return RecipeItemRead.model_validate(recipe_item)


@router.post(
    "",
    response_model=RecipeItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recipe_item(
    recipe_item_in: RecipeItemCreate,
    session: SessionDependency,
) -> RecipeItemRead:
    try:
        recipe_item = await recipe_item_service.create_recipe_item(
            session,
            recipe_item_in,
        )
    except recipe_item_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Menu item not found.",
        ) from exc
    except recipe_item_service.IngredientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ingredient not found.",
        ) from exc
    except recipe_item_service.RecipeItemConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This ingredient is already assigned to the menu item.",
        ) from exc
    return RecipeItemRead.model_validate(recipe_item)


@router.patch("/{recipe_item_id}", response_model=RecipeItemRead)
async def update_recipe_item(
    recipe_item_id: int,
    recipe_item_in: RecipeItemUpdate,
    session: SessionDependency,
) -> RecipeItemRead:
    try:
        recipe_item = await recipe_item_service.update_recipe_item(
            session,
            recipe_item_id,
            recipe_item_in,
        )
    except recipe_item_service.RecipeItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipe item not found.",
        ) from exc
    except recipe_item_service.MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Menu item not found.",
        ) from exc
    except recipe_item_service.IngredientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ingredient not found.",
        ) from exc
    except recipe_item_service.RecipeItemConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This ingredient is already assigned to the menu item.",
        ) from exc
    return RecipeItemRead.model_validate(recipe_item)


@router.delete(
    "/{recipe_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_recipe_item(
    recipe_item_id: int,
    session: SessionDependency,
) -> Response:
    try:
        await recipe_item_service.delete_recipe_item(session, recipe_item_id)
    except recipe_item_service.RecipeItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipe item not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
