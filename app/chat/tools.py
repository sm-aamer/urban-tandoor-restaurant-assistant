from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import schemas
from app.repositories import chat_read

ToolResult = dict[str, object]


class ChatToolError(ValueError):
    pass


class UnknownChatToolError(ChatToolError):
    pass


class InvalidChatToolArgumentsError(ChatToolError):
    pass


async def _list_result[
    PaginatedArgumentsT: schemas.PaginatedToolArguments
](
    session: AsyncSession,
    arguments: PaginatedArgumentsT,
    retrieval: Callable[
        [AsyncSession, PaginatedArgumentsT],
        Awaitable[list[chat_read.ChatRow]],
    ],
) -> ToolResult:
    items = await retrieval(session, arguments)
    return {
        "items": items,
        "count": len(items),
        "limit": arguments.limit,
        "offset": arguments.offset,
    }


async def list_branches(
    session: AsyncSession,
    arguments: schemas.ListBranchesArguments,
) -> ToolResult:
    return await _list_result(session, arguments, chat_read.list_branches)


async def get_branch(
    session: AsyncSession,
    arguments: schemas.RecordIdArguments,
) -> ToolResult:
    branch = await chat_read.get_branch(session, arguments)
    return {"found": branch is not None, "item": branch}


async def list_suppliers(
    session: AsyncSession,
    arguments: schemas.ListSuppliersArguments,
) -> ToolResult:
    return await _list_result(session, arguments, chat_read.list_suppliers)


def _ingredient_with_currency(ingredient: chat_read.ChatRow) -> chat_read.ChatRow:
    return {**ingredient, "currency": "PKR"}


async def search_ingredients(
    session: AsyncSession,
    arguments: schemas.SearchIngredientsArguments,
) -> ToolResult:
    items = await chat_read.search_ingredients(session, arguments)
    return {
        "items": [_ingredient_with_currency(item) for item in items],
        "count": len(items),
        "limit": arguments.limit,
        "offset": arguments.offset,
    }


async def get_ingredient(
    session: AsyncSession,
    arguments: schemas.RecordIdArguments,
) -> ToolResult:
    ingredient = await chat_read.get_ingredient(session, arguments)
    if ingredient is not None:
        ingredient = _ingredient_with_currency(ingredient)
    return {"found": ingredient is not None, "item": ingredient}


async def search_menu_items(
    session: AsyncSession,
    arguments: schemas.SearchMenuItemsArguments,
) -> ToolResult:
    return await _list_result(session, arguments, chat_read.search_menu_items)


async def get_menu_item(
    session: AsyncSession,
    arguments: schemas.RecordIdArguments,
) -> ToolResult:
    menu_item = await chat_read.get_menu_item(session, arguments)
    return {"found": menu_item is not None, "item": menu_item}


async def list_recipe_ingredients(
    session: AsyncSession,
    arguments: schemas.RecipeIngredientsArguments,
) -> ToolResult:
    found, items = await chat_read.list_recipe_ingredients(session, arguments)
    return {"found": found, "items": items, "count": len(items)}


async def list_menu_availability(
    session: AsyncSession,
    arguments: schemas.MenuAvailabilityArguments,
) -> ToolResult:
    found, items = await chat_read.list_menu_availability(session, arguments)
    return {
        "found": found,
        "items": items,
        "count": len(items),
        "limit": arguments.limit,
        "offset": arguments.offset,
    }


async def list_stock_movements(
    session: AsyncSession,
    arguments: schemas.StockMovementArguments,
) -> ToolResult:
    items = await chat_read.list_stock_movements(session, arguments)
    return {
        "items": items,
        "count": len(items),
        "limit": arguments.limit,
        "offset": arguments.offset,
    }


APPROVED_TOOLS = MappingProxyType(
    {
        "list_branches": schemas.ListBranchesArguments,
        "get_branch": schemas.RecordIdArguments,
        "list_suppliers": schemas.ListSuppliersArguments,
        "search_ingredients": schemas.SearchIngredientsArguments,
        "get_ingredient": schemas.RecordIdArguments,
        "search_menu_items": schemas.SearchMenuItemsArguments,
        "get_menu_item": schemas.RecordIdArguments,
        "list_recipe_ingredients": schemas.RecipeIngredientsArguments,
        "list_menu_availability": schemas.MenuAvailabilityArguments,
        "list_stock_movements": schemas.StockMovementArguments,
    }
)


def _validate_arguments[ArgumentsT: BaseModel](
    arguments_model: type[ArgumentsT],
    arguments: Mapping[str, object],
) -> ArgumentsT:
    try:
        return arguments_model.model_validate(arguments)
    except ValidationError as exc:
        raise InvalidChatToolArgumentsError(
            "Invalid arguments for the requested chat tool."
        ) from exc


async def execute_tool(
    session: AsyncSession,
    tool_name: str,
    arguments: Mapping[str, object],
) -> ToolResult:
    if tool_name not in APPROVED_TOOLS:
        raise UnknownChatToolError("Unknown or unapproved chat tool.")

    match tool_name:
        case "list_branches":
            return await list_branches(
                session,
                _validate_arguments(schemas.ListBranchesArguments, arguments),
            )
        case "get_branch":
            return await get_branch(
                session,
                _validate_arguments(schemas.RecordIdArguments, arguments),
            )
        case "list_suppliers":
            return await list_suppliers(
                session,
                _validate_arguments(schemas.ListSuppliersArguments, arguments),
            )
        case "search_ingredients":
            return await search_ingredients(
                session,
                _validate_arguments(schemas.SearchIngredientsArguments, arguments),
            )
        case "get_ingredient":
            return await get_ingredient(
                session,
                _validate_arguments(schemas.RecordIdArguments, arguments),
            )
        case "search_menu_items":
            return await search_menu_items(
                session,
                _validate_arguments(schemas.SearchMenuItemsArguments, arguments),
            )
        case "get_menu_item":
            return await get_menu_item(
                session,
                _validate_arguments(schemas.RecordIdArguments, arguments),
            )
        case "list_recipe_ingredients":
            return await list_recipe_ingredients(
                session,
                _validate_arguments(schemas.RecipeIngredientsArguments, arguments),
            )
        case "list_menu_availability":
            return await list_menu_availability(
                session,
                _validate_arguments(schemas.MenuAvailabilityArguments, arguments),
            )
        case "list_stock_movements":
            return await list_stock_movements(
                session,
                _validate_arguments(schemas.StockMovementArguments, arguments),
            )
        case _:
            raise UnknownChatToolError("Unknown or unapproved chat tool.")
