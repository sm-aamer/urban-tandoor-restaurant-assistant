from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import schemas, tools
from app.repositories import chat_read


def make_session(
    *,
    rows: list[dict[str, object]] | None = None,
    one: dict[str, object] | None = None,
    scalar: object = 1,
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.mappings.return_value.all.return_value = rows or []
    result.mappings.return_value.one_or_none.return_value = one
    session.execute.return_value = result
    session.scalar.return_value = scalar
    return session


def compiled_sql(session: AsyncMock, call: int = 0) -> tuple[str, dict[str, object]]:
    statement = session.execute.await_args_list[call].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


async def test_list_branches_filters_and_bounds_results() -> None:
    session = make_session(rows=[{"id": 1, "branch_code": "UTG-1"}])
    arguments = schemas.ListBranchesArguments(is_active=False, limit=7, offset=4)

    branches = await chat_read.list_branches(session, arguments)

    sql, params = compiled_sql(session)
    assert branches == [{"id": 1, "branch_code": "UTG-1"}]
    assert "branch.is_active =" in sql
    assert "ORDER BY branch.branch_code" in sql
    assert "branch.is_active = false" in sql
    assert 7 in params.values()
    assert 4 in params.values()
    session.execute.assert_awaited_once()


async def test_list_branches_can_filter_active_records() -> None:
    for is_active in (True, False):
        session = make_session()
        await chat_read.list_branches(
            session,
            schemas.ListBranchesArguments(is_active=is_active),
        )
        sql, _ = compiled_sql(session)
        expected_filter = f"branch.is_active = {str(is_active).lower()}"
        assert expected_filter in sql


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"id": 4, "branch_code": "UTG-4"}, {"found": True, "item": {"id": 4, "branch_code": "UTG-4"}}),
        (None, {"found": False, "item": None}),
    ],
)
async def test_get_branch_distinguishes_missing_record(
    row: dict[str, object] | None,
    expected: dict[str, object],
) -> None:
    session = make_session(one=row)
    result = await tools.get_branch(session, schemas.RecordIdArguments(record_id=4))
    assert result == expected


async def test_list_suppliers_omits_contact_information() -> None:
    session = make_session(rows=[{"supplier_code": "SUP-1", "name": "Supplier"}])

    suppliers = await chat_read.list_suppliers(
        session,
        schemas.ListSuppliersArguments(is_active=True),
    )

    sql, _ = compiled_sql(session)
    assert suppliers == [{"supplier_code": "SUP-1", "name": "Supplier"}]
    assert "supplier.contact" not in sql
    assert "contact" not in suppliers[0]
    assert "supplier.is_active = true" in sql


async def test_search_ingredients_uses_bound_escaped_search_and_filters() -> None:
    session = make_session()
    query = "%' OR 1=1 --"
    await chat_read.search_ingredients(
        session,
        schemas.SearchIngredientsArguments(
            query=query,
            category="Grains",
            is_active=True,
        ),
    )

    sql, params = compiled_sql(session)
    assert "ingredient.name ILIKE" in sql
    assert "ingredient.ingredient_code ILIKE" in sql
    assert query not in sql
    assert "%\\%' OR 1=1 --%" in params.values()
    assert "Grains" in params.values()
    assert "ingredient.is_active = true" in sql


async def test_search_ingredients_empty_results_are_an_empty_list() -> None:
    session = make_session(rows=[])
    result = await tools.search_ingredients(
        session,
        schemas.SearchIngredientsArguments(query="not-found"),
    )
    assert result["items"] == []
    assert result["count"] == 0


async def test_get_ingredient_preserves_unknown_price_and_stringifies_decimal() -> None:
    session = make_session(
        one={
            "id": 2,
            "unit_cost_pkr": Decimal("12.50"),
            "name": "Rice",
        }
    )

    result = await tools.get_ingredient(
        session,
        schemas.RecordIdArguments(record_id=2),
    )

    assert result["found"] is True
    assert result["item"]["currency"] == "PKR"
    assert result["item"]["unit_cost_pkr"] == "12.50"


async def test_search_ingredients_includes_pkr_currency_and_preserves_cost() -> None:
    session = make_session(
        rows=[
            {
                "id": 2,
                "name": "Rice",
                "unit_cost_pkr": Decimal("12.50"),
            }
        ]
    )

    result = await tools.search_ingredients(
        session,
        schemas.SearchIngredientsArguments(query="rice"),
    )

    assert result["items"] == [
        {
            "id": 2,
            "name": "Rice",
            "unit_cost_pkr": "12.50",
            "currency": "PKR",
        }
    ]


async def test_search_menu_items_filters_and_returns_price() -> None:
    session = make_session(
        rows=[{"menu_code": "MENU-1", "price_pkr": Decimal("450.00")}]
    )
    result = await tools.search_menu_items(
        session,
        schemas.SearchMenuItemsArguments(query="karahi", is_active=True),
    )

    sql, _ = compiled_sql(session)
    assert result["items"][0]["price_pkr"] == "450.00"
    assert "menu_item.name ILIKE" in sql
    assert "menu_item.menu_code ILIKE" in sql
    assert "karahi" not in sql
    assert "menu_item.is_active = true" in sql


async def test_get_menu_item_reports_missing_record() -> None:
    session = make_session(one=None)
    result = await tools.get_menu_item(
        session,
        schemas.RecordIdArguments(record_id=99),
    )
    assert result == {"found": False, "item": None}


async def test_recipe_query_distinguishes_missing_parent_from_empty_recipe() -> None:
    missing_parent = make_session(scalar=None)
    found, items = await chat_read.list_recipe_ingredients(
        missing_parent,
        schemas.RecipeIngredientsArguments(menu_item_id=100),
    )
    assert (found, items) == (False, [])
    missing_parent.execute.assert_not_awaited()

    empty_recipe = make_session(scalar=7, rows=[])
    result = await tools.list_recipe_ingredients(
        empty_recipe,
        schemas.RecipeIngredientsArguments(menu_item_id=7),
    )
    assert result == {"found": True, "items": [], "count": 0}
    sql, params = compiled_sql(empty_recipe)
    assert "JOIN recipe_item" in sql
    assert 7 in params.values()


async def test_recipe_results_include_ingredient_and_exact_quantity() -> None:
    session = make_session(
        scalar=7,
        rows=[
            {
                "ingredient_id": 2,
                "ingredient_name": "Rice",
                "quantity_per_portion": Decimal("0.250"),
            }
        ],
    )
    result = await tools.list_recipe_ingredients(
        session,
        schemas.RecipeIngredientsArguments(menu_item_id=7),
    )
    assert result["found"] is True
    assert result["items"][0]["ingredient_name"] == "Rice"
    assert result["items"][0]["quantity_per_portion"] == "0.250"


async def test_availability_preserves_null_and_false_values() -> None:
    for available in (True, False, None):
        session = make_session(
            scalar=3,
            rows=[{"is_available": available, "menu_item_name": "Biryani"}],
        )
        result = await tools.list_menu_availability(
            session,
            schemas.MenuAvailabilityArguments(branch_id=3),
        )
        assert result["found"] is True
        assert result["items"][0]["is_available"] is available
        sql, params = compiled_sql(session)
        assert "JOIN menu_availability" in sql
        assert "JOIN menu_item" in sql
        assert 3 in params.values()


async def test_availability_distinguishes_missing_branch_from_no_records() -> None:
    missing_branch = make_session(scalar=None)
    result = await tools.list_menu_availability(
        missing_branch,
        schemas.MenuAvailabilityArguments(branch_id=20),
    )
    assert result["found"] is False
    assert result["items"] == []
    missing_branch.execute.assert_not_awaited()

    no_records = make_session(scalar=20, rows=[])
    result = await tools.list_menu_availability(
        no_records,
        schemas.MenuAvailabilityArguments(branch_id=20, menu_item_id=5),
    )
    assert result["found"] is True
    assert result["items"] == []
    sql, params = compiled_sql(no_records)
    assert "menu_availability.menu_item_id =" in sql
    assert 5 in params.values()


async def test_list_stock_movements_joins_and_serializes_history() -> None:
    movement_date = date(2026, 11, 20)
    session = make_session(
        rows=[
            {
                "movement_id": 12,
                "movement_code": "MOV-12",
                "branch_name": "Karachi",
                "branch_code": "KHI-1",
                "ingredient_name": "Chicken",
                "unit": "kg",
                "movement_type": "IN",
                "quantity": Decimal("12.500"),
                "movement_date": movement_date,
            }
        ]
    )
    arguments = schemas.StockMovementArguments(
        branch_id=3,
        ingredient_id=8,
        movement_type="IN",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        limit=10,
        offset=2,
    )

    result = await tools.list_stock_movements(session, arguments)

    assert result == {
        "items": [
            {
                "movement_id": 12,
                "movement_code": "MOV-12",
                "branch_name": "Karachi",
                "branch_code": "KHI-1",
                "ingredient_name": "Chicken",
                "unit": "kg",
                "movement_type": "IN",
                "quantity": "12.500",
                "movement_date": "2026-11-20",
            }
        ],
        "count": 1,
        "limit": 10,
        "offset": 2,
    }

    sql, params = compiled_sql(session)
    assert "JOIN branch ON stock_movement.branch_id = branch.id" in sql
    assert "JOIN ingredient ON stock_movement.ingredient_id = ingredient.id" in sql
    for selected_field in (
        "stock_movement.id AS movement_id",
        "stock_movement.movement_code",
        "branch.name AS branch_name",
        "branch.branch_code",
        "ingredient.name AS ingredient_name",
        "ingredient.unit",
        "stock_movement.movement_type",
        "stock_movement.quantity",
        "stock_movement.movement_date",
    ):
        assert selected_field in sql
    assert "stock_movement.branch_id =" in sql
    assert "stock_movement.ingredient_id =" in sql
    assert "stock_movement.movement_type =" in sql
    assert "stock_movement.movement_date >=" in sql
    assert "stock_movement.movement_date <=" in sql
    assert "ORDER BY stock_movement.movement_date DESC, stock_movement.id DESC" in sql
    assert {3, 8, "IN", date(2026, 11, 1), date(2026, 11, 30), 10, 2}.issubset(
        set(params.values())
    )


async def test_list_stock_movements_returns_empty_page() -> None:
    session = make_session(rows=[])

    result = await tools.execute_tool(session, "list_stock_movements", {})

    assert result == {"items": [], "count": 0, "limit": 20, "offset": 0}
    sql, _ = compiled_sql(session)
    assert sql.lstrip().startswith("SELECT")


@pytest.mark.parametrize(
    "arguments",
    [
        {"branch_id": 0},
        {"ingredient_id": -1},
        {"movement_type": ""},
        {"movement_type": "x" * 41},
        {"start_date": "2026-12-01", "end_date": "2026-11-01"},
        {"limit": 51},
        {"unexpected": True},
    ],
)
def test_stock_movement_arguments_reject_invalid_values(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.StockMovementArguments.model_validate(arguments)


def test_stock_movement_arguments_parse_iso_dates_and_enforce_page_limit() -> None:
    arguments = schemas.StockMovementArguments.model_validate(
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
            "limit": 50,
        }
    )

    assert arguments.start_date == date(2026, 11, 1)
    assert arguments.end_date == date(2026, 11, 30)
    assert schemas.StockMovementArguments().limit == 20
    assert arguments.limit == 50


@pytest.mark.parametrize(
    "arguments",
    [
        {"record_id": 0},
        {"record_id": -1},
        {"record_id": True},
        {"record_id": "1"},
        {"record_id": 1, "unexpected": True},
        {"record_id": "1; DROP TABLE branch"},
    ],
)
async def test_tool_arguments_reject_invalid_ids_and_extra_fields(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.RecordIdArguments.model_validate(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": 51},
        {"offset": -1},
        {"query": ""},
        {"query": "x" * 101},
        {"category": "x" * 121},
        {"menu_item_id": 1, "limit": 51},
        {"branch_id": 0},
    ],
)
async def test_tool_argument_schemas_enforce_bounds(
    arguments: dict[str, object],
) -> None:
    schema: type[schemas.ToolArguments]
    if "menu_item_id" in arguments:
        schema = schemas.RecipeIngredientsArguments
    elif "branch_id" in arguments:
        schema = schemas.MenuAvailabilityArguments
    elif "query" in arguments or "category" in arguments:
        schema = schemas.SearchIngredientsArguments
    else:
        schema = schemas.ListBranchesArguments

    with pytest.raises(ValidationError):
        schema.model_validate(arguments)


async def test_execute_tool_rejects_unapproved_names_without_database_access() -> None:
    session = make_session()

    with pytest.raises(tools.UnknownChatToolError):
        await tools.execute_tool(session, "execute_sql", {"query": "SELECT 1"})

    session.execute.assert_not_awaited()
    session.scalar.assert_not_awaited()


async def test_execute_tool_returns_sanitized_validation_error() -> None:
    session = make_session()

    with pytest.raises(tools.InvalidChatToolArgumentsError) as error:
        await tools.execute_tool(
            session,
            "get_branch",
            {"record_id": 1, "secret": "not returned"},
        )

    assert "not returned" not in str(error.value)
    session.execute.assert_not_awaited()


async def test_approved_read_tools_execute_only_select_statements() -> None:
    session = make_session(rows=[])

    await tools.execute_tool(session, "list_branches", {})
    await tools.execute_tool(session, "get_branch", {"record_id": 1})
    await tools.execute_tool(session, "list_suppliers", {})
    await tools.execute_tool(session, "search_ingredients", {"query": "rice"})
    await tools.execute_tool(session, "get_ingredient", {"record_id": 1})
    await tools.execute_tool(session, "search_menu_items", {"query": "karahi"})
    await tools.execute_tool(session, "get_menu_item", {"record_id": 1})
    await tools.execute_tool(
        session,
        "list_recipe_ingredients",
        {"menu_item_id": 1},
    )
    await tools.execute_tool(
        session,
        "list_menu_availability",
        {"branch_id": 1},
    )
    await tools.execute_tool(session, "list_stock_movements", {})

    for call in session.execute.await_args_list:
        statement = call.args[0]
        assert not isinstance(statement, str)
        assert str(statement.compile(dialect=postgresql.dialect())).lstrip().startswith(
            "SELECT"
        )
    for call in session.scalar.await_args_list:
        statement = call.args[0]
        assert not isinstance(statement, str)
        assert str(statement.compile(dialect=postgresql.dialect())).lstrip().startswith(
            "SELECT"
        )
    session.add.assert_not_called()
    session.delete.assert_not_called()
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()
