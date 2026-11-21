from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Ingredient, MenuItem, RecipeItem


async def list_recipe_items(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    menu_item_id: int | None,
    ingredient_id: int | None,
) -> tuple[list[RecipeItem], int]:
    filters = []
    if menu_item_id is not None:
        filters.append(RecipeItem.menu_item_id == menu_item_id)
    if ingredient_id is not None:
        filters.append(RecipeItem.ingredient_id == ingredient_id)

    statement = select(RecipeItem).where(*filters).order_by(RecipeItem.id)
    result = await session.execute(statement.offset(offset).limit(limit))
    recipe_items = list(result.scalars().all())

    count_statement = select(func.count()).select_from(RecipeItem).where(*filters)
    total = await session.scalar(count_statement)
    return recipe_items, total or 0


async def get_recipe_item(
    session: AsyncSession,
    recipe_item_id: int,
) -> RecipeItem | None:
    return await session.get(RecipeItem, recipe_item_id)


async def menu_item_exists(session: AsyncSession, menu_item_id: int) -> bool:
    return await session.get(MenuItem, menu_item_id) is not None


async def ingredient_exists(session: AsyncSession, ingredient_id: int) -> bool:
    return await session.get(Ingredient, ingredient_id) is not None


async def combination_exists(
    session: AsyncSession,
    menu_item_id: int,
    ingredient_id: int,
    *,
    exclude_recipe_item_id: int | None = None,
) -> bool:
    statement = select(RecipeItem.id).where(
        RecipeItem.menu_item_id == menu_item_id,
        RecipeItem.ingredient_id == ingredient_id,
    )
    if exclude_recipe_item_id is not None:
        statement = statement.where(RecipeItem.id != exclude_recipe_item_id)
    return await session.scalar(statement) is not None


async def create_recipe_item(
    session: AsyncSession,
    recipe_item: RecipeItem,
) -> RecipeItem:
    session.add(recipe_item)
    await session.flush()
    return recipe_item


async def save_recipe_item(
    session: AsyncSession,
    recipe_item: RecipeItem,
) -> RecipeItem:
    await session.flush()
    return recipe_item


async def delete_recipe_item(
    session: AsyncSession,
    recipe_item: RecipeItem,
) -> None:
    await session.delete(recipe_item)
    await session.flush()
