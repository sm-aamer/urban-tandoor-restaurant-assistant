from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecipeItem
from app.repositories import recipe_item as recipe_item_repository
from app.schemas.recipe_item import RecipeItemCreate, RecipeItemUpdate


class RecipeItemNotFoundError(Exception):
    pass


class RecipeItemConflictError(Exception):
    pass


class MenuItemNotFoundError(Exception):
    pass


class IngredientNotFoundError(Exception):
    pass


async def list_recipe_items(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    menu_item_id: int | None,
    ingredient_id: int | None,
) -> tuple[list[RecipeItem], int]:
    return await recipe_item_repository.list_recipe_items(
        session,
        limit=limit,
        offset=offset,
        menu_item_id=menu_item_id,
        ingredient_id=ingredient_id,
    )


async def get_recipe_item(
    session: AsyncSession,
    recipe_item_id: int,
) -> RecipeItem:
    recipe_item = await recipe_item_repository.get_recipe_item(
        session,
        recipe_item_id,
    )
    if recipe_item is None:
        raise RecipeItemNotFoundError
    return recipe_item


async def _validate_parents(
    session: AsyncSession,
    menu_item_id: int,
    ingredient_id: int,
) -> None:
    if not await recipe_item_repository.menu_item_exists(session, menu_item_id):
        raise MenuItemNotFoundError
    if not await recipe_item_repository.ingredient_exists(session, ingredient_id):
        raise IngredientNotFoundError


async def create_recipe_item(
    session: AsyncSession,
    recipe_item_in: RecipeItemCreate,
) -> RecipeItem:
    try:
        async with session.begin():
            await _validate_parents(
                session,
                recipe_item_in.menu_item_id,
                recipe_item_in.ingredient_id,
            )
            if await recipe_item_repository.combination_exists(
                session,
                recipe_item_in.menu_item_id,
                recipe_item_in.ingredient_id,
            ):
                raise RecipeItemConflictError
            recipe_item = RecipeItem(**recipe_item_in.model_dump())
            await recipe_item_repository.create_recipe_item(session, recipe_item)
    except IntegrityError as exc:
        raise RecipeItemConflictError from exc
    return recipe_item


async def update_recipe_item(
    session: AsyncSession,
    recipe_item_id: int,
    recipe_item_in: RecipeItemUpdate,
) -> RecipeItem:
    try:
        async with session.begin():
            recipe_item = await recipe_item_repository.get_recipe_item(
                session,
                recipe_item_id,
            )
            if recipe_item is None:
                raise RecipeItemNotFoundError

            updates = recipe_item_in.model_dump(exclude_unset=True)
            menu_item_id = updates.get("menu_item_id", recipe_item.menu_item_id)
            ingredient_id = updates.get("ingredient_id", recipe_item.ingredient_id)
            if "menu_item_id" in updates or "ingredient_id" in updates:
                await _validate_parents(session, menu_item_id, ingredient_id)
                if await recipe_item_repository.combination_exists(
                    session,
                    menu_item_id,
                    ingredient_id,
                    exclude_recipe_item_id=recipe_item_id,
                ):
                    raise RecipeItemConflictError

            for field, value in updates.items():
                setattr(recipe_item, field, value)
            await recipe_item_repository.save_recipe_item(session, recipe_item)
    except IntegrityError as exc:
        raise RecipeItemConflictError from exc
    return recipe_item


async def delete_recipe_item(
    session: AsyncSession,
    recipe_item_id: int,
) -> None:
    async with session.begin():
        recipe_item = await recipe_item_repository.get_recipe_item(
            session,
            recipe_item_id,
        )
        if recipe_item is None:
            raise RecipeItemNotFoundError
        await recipe_item_repository.delete_recipe_item(session, recipe_item)
