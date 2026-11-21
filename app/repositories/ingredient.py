from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Ingredient, Supplier


async def list_ingredients(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
    category: str | None,
    supplier_id: int | None,
) -> tuple[list[Ingredient], int]:
    filters = []
    if is_active is not None:
        filters.append(Ingredient.is_active == is_active)
    if category is not None:
        filters.append(Ingredient.category == category)
    if supplier_id is not None:
        filters.append(Ingredient.supplier_id == supplier_id)

    statement = (
        select(Ingredient)
        .where(*filters)
        .order_by(Ingredient.ingredient_code)
    )
    result = await session.execute(statement.offset(offset).limit(limit))
    ingredients = list(result.scalars().all())

    count_statement = (
        select(func.count()).select_from(Ingredient).where(*filters)
    )
    total = await session.scalar(count_statement)
    return ingredients, total or 0


async def get_ingredient(
    session: AsyncSession,
    ingredient_id: int,
) -> Ingredient | None:
    return await session.get(Ingredient, ingredient_id)


async def supplier_exists(session: AsyncSession, supplier_id: int) -> bool:
    return await session.get(Supplier, supplier_id) is not None


async def create_ingredient(
    session: AsyncSession,
    ingredient: Ingredient,
) -> Ingredient:
    session.add(ingredient)
    await session.flush()
    return ingredient


async def save_ingredient(
    session: AsyncSession,
    ingredient: Ingredient,
) -> Ingredient:
    await session.flush()
    return ingredient
