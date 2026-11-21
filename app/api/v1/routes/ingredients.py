from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.schemas.ingredient import (
    IngredientCreate,
    IngredientListResponse,
    IngredientRead,
    IngredientUpdate,
)
from app.services import ingredient as ingredient_service

router = APIRouter(prefix="/ingredients", tags=["ingredients"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=IngredientListResponse)
async def list_ingredients(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    is_active: bool | None = None,
    category: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    supplier_id: Annotated[int | None, Query(ge=1)] = None,
) -> IngredientListResponse:
    ingredients, total = await ingredient_service.list_ingredients(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
        category=category,
        supplier_id=supplier_id,
    )
    return IngredientListResponse(
        items=[IngredientRead.model_validate(ingredient) for ingredient in ingredients],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{ingredient_id}", response_model=IngredientRead)
async def get_ingredient(
    ingredient_id: int,
    session: SessionDependency,
) -> IngredientRead:
    try:
        ingredient = await ingredient_service.get_ingredient(session, ingredient_id)
    except ingredient_service.IngredientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingredient not found.",
        ) from exc
    return IngredientRead.model_validate(ingredient)


@router.post(
    "",
    response_model=IngredientRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ingredient(
    ingredient_in: IngredientCreate,
    session: SessionDependency,
) -> IngredientRead:
    try:
        ingredient = await ingredient_service.create_ingredient(session, ingredient_in)
    except ingredient_service.SupplierNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Supplier not found.",
        ) from exc
    except ingredient_service.IngredientConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingredient with this ingredient code already exists.",
        ) from exc
    return IngredientRead.model_validate(ingredient)


@router.patch("/{ingredient_id}", response_model=IngredientRead)
async def update_ingredient(
    ingredient_id: int,
    ingredient_in: IngredientUpdate,
    session: SessionDependency,
) -> IngredientRead:
    try:
        ingredient = await ingredient_service.update_ingredient(
            session,
            ingredient_id,
            ingredient_in,
        )
    except ingredient_service.IngredientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingredient not found.",
        ) from exc
    except ingredient_service.SupplierNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Supplier not found.",
        ) from exc
    except ingredient_service.IngredientConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingredient with this ingredient code already exists.",
        ) from exc
    return IngredientRead.model_validate(ingredient)


@router.delete(
    "/{ingredient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_ingredient(
    ingredient_id: int,
    session: SessionDependency,
) -> Response:
    try:
        await ingredient_service.deactivate_ingredient(session, ingredient_id)
    except ingredient_service.IngredientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingredient not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
