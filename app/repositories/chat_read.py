from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.chat.schemas import (
    ListBranchesArguments,
    ListSuppliersArguments,
    MenuAvailabilityArguments,
    RecipeIngredientsArguments,
    RecordIdArguments,
    SearchIngredientsArguments,
    SearchMenuItemsArguments,
    StockMovementArguments,
)
from app.models import (
    Branch,
    Ingredient,
    MenuAvailability,
    MenuItem,
    RecipeItem,
    StockMovement,
    Supplier,
)

ChatRow = dict[str, object]


def _serialize_rows(rows: Sequence[Mapping[str, object]]) -> list[ChatRow]:
    serialized: list[ChatRow] = []
    for row in rows:
        values = dict(row)
        serialized.append(
            {
                key: (
                    str(value)
                    if isinstance(value, Decimal)
                    else value.isoformat()
                    if isinstance(value, date)
                    else value
                )
                for key, value in values.items()
            }
        )
    return serialized


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_branches(
    session: AsyncSession,
    arguments: ListBranchesArguments,
) -> list[ChatRow]:
    statement = select(
        Branch.id,
        Branch.branch_code,
        Branch.name,
        Branch.address,
        Branch.operating_hours,
        Branch.is_active,
    )
    if arguments.is_active is not None:
        statement = statement.where(Branch.is_active == arguments.is_active)
    statement = (
        statement.order_by(Branch.branch_code)
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return _serialize_rows(list(result.mappings().all()))


async def get_branch(
    session: AsyncSession,
    arguments: RecordIdArguments,
) -> ChatRow | None:
    statement = select(
        Branch.id,
        Branch.branch_code,
        Branch.name,
        Branch.address,
        Branch.table_count,
        Branch.seat_capacity,
        Branch.operating_hours,
        Branch.is_active,
    ).where(Branch.id == arguments.record_id)
    result = await session.execute(statement)
    row = result.mappings().one_or_none()
    return _serialize_rows([row])[0] if row is not None else None


async def list_suppliers(
    session: AsyncSession,
    arguments: ListSuppliersArguments,
) -> list[ChatRow]:
    statement = select(
        Supplier.id,
        Supplier.supplier_code,
        Supplier.name,
        Supplier.supply_category,
        Supplier.verification_status,
        Supplier.is_active,
    )
    if arguments.is_active is not None:
        statement = statement.where(Supplier.is_active == arguments.is_active)
    statement = (
        statement.order_by(Supplier.supplier_code)
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return _serialize_rows(list(result.mappings().all()))


async def search_ingredients(
    session: AsyncSession,
    arguments: SearchIngredientsArguments,
) -> list[ChatRow]:
    statement = select(
        Ingredient.id,
        Ingredient.ingredient_code,
        Ingredient.name,
        Ingredient.category,
        Ingredient.unit,
        Ingredient.unit_cost_pkr,
        Ingredient.is_active,
    )
    if arguments.query is not None:
        pattern = f"%{_escape_like(arguments.query)}%"
        statement = statement.where(
            Ingredient.name.ilike(pattern, escape="\\")
            | Ingredient.ingredient_code.ilike(pattern, escape="\\")
        )
    if arguments.category is not None:
        statement = statement.where(Ingredient.category == arguments.category)
    if arguments.is_active is not None:
        statement = statement.where(Ingredient.is_active == arguments.is_active)
    statement = (
        statement.order_by(Ingredient.ingredient_code)
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return _serialize_rows(list(result.mappings().all()))


async def get_ingredient(
    session: AsyncSession,
    arguments: RecordIdArguments,
) -> ChatRow | None:
    statement = select(
        Ingredient.id,
        Ingredient.ingredient_code,
        Ingredient.name,
        Ingredient.category,
        Ingredient.unit,
        Ingredient.unit_cost_pkr,
        Ingredient.default_reorder_quantity,
        Ingredient.default_target_quantity,
        Ingredient.is_active,
    ).where(Ingredient.id == arguments.record_id)
    result = await session.execute(statement)
    row = result.mappings().one_or_none()
    return _serialize_rows([row])[0] if row is not None else None


async def search_menu_items(
    session: AsyncSession,
    arguments: SearchMenuItemsArguments,
) -> list[ChatRow]:
    statement = select(
        MenuItem.id,
        MenuItem.menu_code,
        MenuItem.name,
        MenuItem.category,
        MenuItem.price_pkr,
        MenuItem.is_active,
    )
    if arguments.query is not None:
        pattern = f"%{_escape_like(arguments.query)}%"
        statement = statement.where(
            MenuItem.name.ilike(pattern, escape="\\")
            | MenuItem.menu_code.ilike(pattern, escape="\\")
        )
    if arguments.is_active is not None:
        statement = statement.where(MenuItem.is_active == arguments.is_active)
    statement = (
        statement.order_by(MenuItem.menu_code)
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return _serialize_rows(list(result.mappings().all()))


async def get_menu_item(
    session: AsyncSession,
    arguments: RecordIdArguments,
) -> ChatRow | None:
    statement = select(
        MenuItem.id,
        MenuItem.menu_code,
        MenuItem.name,
        MenuItem.category,
        MenuItem.description,
        MenuItem.price_pkr,
        MenuItem.is_active,
    ).where(MenuItem.id == arguments.record_id)
    result = await session.execute(statement)
    row = result.mappings().one_or_none()
    return _serialize_rows([row])[0] if row is not None else None


async def list_recipe_ingredients(
    session: AsyncSession,
    arguments: RecipeIngredientsArguments,
) -> tuple[bool, list[ChatRow]]:
    menu_item_exists = await session.scalar(
        select(MenuItem.id).where(MenuItem.id == arguments.menu_item_id)
    )
    if menu_item_exists is None:
        return False, []

    statement = (
        select(
            Ingredient.id.label("ingredient_id"),
            Ingredient.ingredient_code,
            Ingredient.name.label("ingredient_name"),
            Ingredient.unit,
            RecipeItem.quantity_per_portion,
        )
        .join(RecipeItem, RecipeItem.ingredient_id == Ingredient.id)
        .where(RecipeItem.menu_item_id == arguments.menu_item_id)
        .order_by(Ingredient.ingredient_code)
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return True, _serialize_rows(list(result.mappings().all()))


async def list_menu_availability(
    session: AsyncSession,
    arguments: MenuAvailabilityArguments,
) -> tuple[bool, list[ChatRow]]:
    branch_exists = await session.scalar(
        select(Branch.id).where(Branch.id == arguments.branch_id)
    )
    if branch_exists is None:
        return False, []

    statement = (
        select(
            Branch.branch_code,
            Branch.name.label("branch_name"),
            MenuItem.id.label("menu_item_id"),
            MenuItem.menu_code,
            MenuItem.name.label("menu_item_name"),
            MenuItem.is_active.label("menu_item_is_active"),
            MenuAvailability.is_available,
        )
        .join(MenuAvailability, MenuAvailability.branch_id == Branch.id)
        .join(MenuItem, MenuAvailability.menu_item_id == MenuItem.id)
        .where(Branch.id == arguments.branch_id)
    )
    if arguments.menu_item_id is not None:
        statement = statement.where(
            MenuAvailability.menu_item_id == arguments.menu_item_id
        )
    statement = (
        statement.order_by(MenuItem.menu_code)
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return True, _serialize_rows(list(result.mappings().all()))


async def list_stock_movements(
    session: AsyncSession,
    arguments: StockMovementArguments,
) -> list[ChatRow]:
    statement = (
        select(
            StockMovement.id.label("movement_id"),
            StockMovement.movement_code,
            Branch.name.label("branch_name"),
            Branch.branch_code,
            Ingredient.name.label("ingredient_name"),
            Ingredient.unit,
            StockMovement.movement_type,
            StockMovement.quantity,
            StockMovement.movement_date,
        )
        .join(Branch, StockMovement.branch_id == Branch.id)
        .join(Ingredient, StockMovement.ingredient_id == Ingredient.id)
    )
    if arguments.branch_id is not None:
        statement = statement.where(StockMovement.branch_id == arguments.branch_id)
    if arguments.ingredient_id is not None:
        statement = statement.where(
            StockMovement.ingredient_id == arguments.ingredient_id
        )
    if arguments.movement_type is not None:
        statement = statement.where(
            StockMovement.movement_type == arguments.movement_type
        )
    if arguments.start_date is not None:
        statement = statement.where(
            StockMovement.movement_date >= arguments.start_date
        )
    if arguments.end_date is not None:
        statement = statement.where(StockMovement.movement_date <= arguments.end_date)
    statement = (
        statement.order_by(
            StockMovement.movement_date.desc(),
            StockMovement.id.desc(),
        )
        .offset(arguments.offset)
        .limit(arguments.limit)
    )
    result = await session.execute(statement)
    return _serialize_rows(list(result.mappings().all()))
