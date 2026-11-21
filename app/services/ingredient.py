from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ingredient
from app.repositories import ingredient as ingredient_repository
from app.schemas.ingredient import IngredientCreate, IngredientUpdate


class IngredientNotFoundError(Exception):
    pass


class IngredientConflictError(Exception):
    pass


class SupplierNotFoundError(Exception):
    pass


async def list_ingredients(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
    category: str | None,
    supplier_id: int | None,
) -> tuple[list[Ingredient], int]:
    return await ingredient_repository.list_ingredients(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
        category=category,
        supplier_id=supplier_id,
    )


async def get_ingredient(
    session: AsyncSession,
    ingredient_id: int,
) -> Ingredient:
    ingredient = await ingredient_repository.get_ingredient(session, ingredient_id)
    if ingredient is None:
        raise IngredientNotFoundError
    return ingredient


async def _validate_supplier(
    session: AsyncSession,
    supplier_id: int | None,
) -> None:
    if supplier_id is not None and not await ingredient_repository.supplier_exists(
        session,
        supplier_id,
    ):
        raise SupplierNotFoundError


async def create_ingredient(
    session: AsyncSession,
    ingredient_in: IngredientCreate,
) -> Ingredient:
    try:
        async with session.begin():
            await _validate_supplier(session, ingredient_in.supplier_id)
            ingredient = Ingredient(**ingredient_in.model_dump())
            await ingredient_repository.create_ingredient(session, ingredient)
    except IntegrityError as exc:
        raise IngredientConflictError from exc
    return ingredient


async def update_ingredient(
    session: AsyncSession,
    ingredient_id: int,
    ingredient_in: IngredientUpdate,
) -> Ingredient:
    try:
        async with session.begin():
            ingredient = await ingredient_repository.get_ingredient(
                session,
                ingredient_id,
            )
            if ingredient is None:
                raise IngredientNotFoundError
            updates = ingredient_in.model_dump(exclude_unset=True)
            if "supplier_id" in updates:
                await _validate_supplier(session, updates["supplier_id"])
            for field, value in updates.items():
                setattr(ingredient, field, value)
            await ingredient_repository.save_ingredient(session, ingredient)
    except IntegrityError as exc:
        raise IngredientConflictError from exc
    return ingredient


async def deactivate_ingredient(
    session: AsyncSession,
    ingredient_id: int,
) -> None:
    async with session.begin():
        ingredient = await ingredient_repository.get_ingredient(session, ingredient_id)
        if ingredient is None:
            raise IngredientNotFoundError
        ingredient.is_active = False
        await ingredient_repository.save_ingredient(session, ingredient)
