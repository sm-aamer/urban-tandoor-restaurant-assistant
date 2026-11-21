from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.main import app
from app.models import RecipeItem
from app.repositories import recipe_item as recipe_item_repository
from app.schemas.recipe_item import RecipeItemCreate, RecipeItemUpdate
from app.services import recipe_item as recipe_item_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RECIPE_ITEM_PAYLOAD = {
    "menu_item_id": 10,
    "ingredient_id": 20,
    "quantity_per_portion": "0.125",
}


def make_recipe_item(**overrides: object) -> RecipeItem:
    values = RECIPE_ITEM_PAYLOAD | {
        "quantity_per_portion": Decimal("0.125"),
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides
    return RecipeItem(id=1, **values)


async def request(
    method: str,
    path: str,
    *,
    session: AsyncSession | None = None,
    **kwargs: object,
) -> httpx.Response:
    fake_session = session or AsyncMock(spec=AsyncSession)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield fake_session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_list_recipe_items_returns_page_and_parent_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_recipe_item()], 1))
    monkeypatch.setattr(recipe_item_service, "list_recipe_items", list_mock)

    response = await request(
        "GET",
        "/api/v1/recipe-items?limit=5&offset=2&menu_item_id=10&ingredient_id=20",
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 2
    assert list_mock.await_args.kwargs == {
        "limit": 5,
        "offset": 2,
        "menu_item_id": 10,
        "ingredient_id": 20,
    }


async def test_repository_list_orders_by_id_and_paginates() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalars.return_value.all.return_value = [make_recipe_item()]
    session.execute.return_value = result
    session.scalar.return_value = 1

    items, total = await recipe_item_repository.list_recipe_items(
        session,
        limit=10,
        offset=20,
        menu_item_id=10,
        ingredient_id=20,
    )

    compiled = session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert "recipe_item.menu_item_id =" in sql
    assert "recipe_item.ingredient_id =" in sql
    assert "ORDER BY recipe_item.id" in sql
    assert "LIMIT" in sql and "OFFSET" in sql
    assert compiled.params["param_1"] == 10
    assert compiled.params["param_2"] == 20
    assert items[0].id == 1
    assert total == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "menu_item_id=0",
        "ingredient_id=0",
    ],
)
async def test_list_recipe_items_rejects_invalid_query(query: str) -> None:
    response = await request("GET", f"/api/v1/recipe-items?{query}")

    assert response.status_code == 422


async def test_get_recipe_item_returns_item_and_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recipe_item_service,
        "get_recipe_item",
        AsyncMock(return_value=make_recipe_item()),
    )

    response = await request("GET", "/api/v1/recipe-items/1")

    assert response.status_code == 200
    assert response.json()["quantity_per_portion"] == "0.125"


async def test_get_recipe_item_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recipe_item_service,
        "get_recipe_item",
        AsyncMock(side_effect=recipe_item_service.RecipeItemNotFoundError),
    )

    response = await request("GET", "/api/v1/recipe-items/999")

    assert response.status_code == 404


async def test_create_recipe_item_returns_201_and_preserves_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_mock = AsyncMock(return_value=make_recipe_item())
    monkeypatch.setattr(recipe_item_service, "create_recipe_item", create_mock)

    response = await request(
        "POST",
        "/api/v1/recipe-items",
        json=RECIPE_ITEM_PAYLOAD,
    )

    assert response.status_code == 201
    assert response.json()["quantity_per_portion"] == "0.125"
    assert isinstance(create_mock.await_args.args[1], RecipeItemCreate)
    assert create_mock.await_args.args[1].quantity_per_portion == Decimal("0.125")


@pytest.mark.parametrize(
    "error,expected_status,detail",
    [
        (
            recipe_item_service.MenuItemNotFoundError,
            422,
            "Menu item not found.",
        ),
        (
            recipe_item_service.IngredientNotFoundError,
            422,
            "Ingredient not found.",
        ),
        (
            recipe_item_service.RecipeItemConflictError,
            409,
            "This ingredient is already assigned to the menu item.",
        ),
    ],
)
async def test_create_recipe_item_maps_parent_errors_and_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    expected_status: int,
    detail: str,
) -> None:
    monkeypatch.setattr(
        recipe_item_service,
        "create_recipe_item",
        AsyncMock(side_effect=error),
    )

    response = await request(
        "POST",
        "/api/v1/recipe-items",
        json=RECIPE_ITEM_PAYLOAD,
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    "payload",
    [
        {"menu_item_id": 10, "quantity_per_portion": "1"},
        RECIPE_ITEM_PAYLOAD | {"id": 99},
        RECIPE_ITEM_PAYLOAD | {"created_at": NOW.isoformat()},
        RECIPE_ITEM_PAYLOAD | {"quantity_per_portion": "0"},
        RECIPE_ITEM_PAYLOAD | {"quantity_per_portion": "-0.001"},
        RECIPE_ITEM_PAYLOAD | {"quantity_per_portion": "0.0001"},
        RECIPE_ITEM_PAYLOAD | {"quantity_per_portion": "1" * 12 + ".000"},
    ],
)
async def test_create_recipe_item_rejects_invalid_fields(
    payload: dict[str, object],
) -> None:
    response = await request("POST", "/api/v1/recipe-items", json=payload)

    assert response.status_code == 422


async def test_update_recipe_item_changes_only_supplied_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(
        return_value=make_recipe_item(quantity_per_portion=Decimal("2.500"))
    )
    monkeypatch.setattr(recipe_item_service, "update_recipe_item", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/recipe-items/1",
        json={"quantity_per_portion": "2.500"},
    )

    assert response.status_code == 200
    assert response.json()["quantity_per_portion"] == "2.500"
    assert update_mock.await_args.args[2].model_dump(exclude_unset=True) == {
        "quantity_per_portion": Decimal("2.500")
    }


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (recipe_item_service.RecipeItemNotFoundError, 404),
        (recipe_item_service.MenuItemNotFoundError, 422),
        (recipe_item_service.IngredientNotFoundError, 422),
        (recipe_item_service.RecipeItemConflictError, 409),
    ],
)
async def test_update_recipe_item_maps_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    expected_status: int,
) -> None:
    monkeypatch.setattr(
        recipe_item_service,
        "update_recipe_item",
        AsyncMock(side_effect=error),
    )

    response = await request(
        "PATCH",
        "/api/v1/recipe-items/1",
        json={"ingredient_id": 21},
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "payload",
    [{}, {"menu_item_id": None}, {"ingredient_id": None}, {"id": 2}],
)
async def test_update_recipe_item_rejects_empty_or_invalid_patch(
    payload: dict[str, object],
) -> None:
    response = await request("PATCH", "/api/v1/recipe-items/1", json=payload)

    assert response.status_code == 422


async def test_delete_recipe_item_physically_deletes_only_relationship(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(recipe_item_service, "delete_recipe_item", delete_mock)

    response = await request("DELETE", "/api/v1/recipe-items/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_recipe_item_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recipe_item_service,
        "delete_recipe_item",
        AsyncMock(side_effect=recipe_item_service.RecipeItemNotFoundError),
    )

    response = await request("DELETE", "/api/v1/recipe-items/999")

    assert response.status_code == 404


def test_recipe_item_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/recipe-items", "get"),
        ("/api/v1/recipe-items", "post"),
        ("/api/v1/recipe-items/{recipe_item_id}", "get"),
        ("/api/v1/recipe-items/{recipe_item_id}", "patch"),
        ("/api/v1/recipe-items/{recipe_item_id}", "delete"),
    }
    actual = {
        (path, method)
        for path, operations in paths.items()
        for method in operations
    }
    assert expected <= actual


class TransactionContext:
    def __init__(self) -> None:
        self.exc_type: type[BaseException] | None = None

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self.exc_type = exc_type


def make_session() -> tuple[AsyncSession, TransactionContext]:
    session = AsyncMock(spec=AsyncSession)
    transaction = TransactionContext()
    session.begin = Mock(return_value=transaction)
    return session, transaction


async def test_service_create_validates_parents_and_uses_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    menu_exists = AsyncMock(return_value=True)
    ingredient_exists = AsyncMock(return_value=True)
    create_mock = AsyncMock(return_value=make_recipe_item())
    monkeypatch.setattr(recipe_item_repository, "menu_item_exists", menu_exists)
    monkeypatch.setattr(recipe_item_repository, "ingredient_exists", ingredient_exists)
    monkeypatch.setattr(recipe_item_repository, "combination_exists", AsyncMock(return_value=False))
    monkeypatch.setattr(recipe_item_repository, "create_recipe_item", create_mock)

    item = await recipe_item_service.create_recipe_item(
        session,
        RecipeItemCreate(**RECIPE_ITEM_PAYLOAD),
    )

    assert item.menu_item_id == 10
    assert item.ingredient_id == 20
    menu_exists.assert_awaited_once_with(session, 10)
    ingredient_exists.assert_awaited_once_with(session, 20)
    assert create_mock.await_args.args[1].quantity_per_portion == Decimal("0.125")
    assert transaction.exc_type is None


@pytest.mark.parametrize(
    "missing_parent,error_type",
    [
        ("menu", recipe_item_service.MenuItemNotFoundError),
        ("ingredient", recipe_item_service.IngredientNotFoundError),
    ],
)
async def test_service_create_rejects_missing_parent_before_create(
    monkeypatch: pytest.MonkeyPatch,
    missing_parent: str,
    error_type: type[Exception],
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        recipe_item_repository,
        "menu_item_exists",
        AsyncMock(return_value=missing_parent != "menu"),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "ingredient_exists",
        AsyncMock(return_value=missing_parent != "ingredient"),
    )
    create_mock = AsyncMock()
    monkeypatch.setattr(recipe_item_repository, "create_recipe_item", create_mock)

    with pytest.raises(error_type):
        await recipe_item_service.create_recipe_item(
            session,
            RecipeItemCreate(**RECIPE_ITEM_PAYLOAD),
        )

    create_mock.assert_not_awaited()
    assert transaction.exc_type is error_type


async def test_service_create_rejects_duplicate_combination_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        recipe_item_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "ingredient_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "combination_exists",
        AsyncMock(return_value=True),
    )
    create_mock = AsyncMock()
    monkeypatch.setattr(recipe_item_repository, "create_recipe_item", create_mock)

    with pytest.raises(recipe_item_service.RecipeItemConflictError):
        await recipe_item_service.create_recipe_item(
            session,
            RecipeItemCreate(**RECIPE_ITEM_PAYLOAD),
        )

    create_mock.assert_not_awaited()
    assert transaction.exc_type is recipe_item_service.RecipeItemConflictError


async def test_service_create_converts_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        recipe_item_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "ingredient_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "combination_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "create_recipe_item",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(recipe_item_service.RecipeItemConflictError) as error:
        await recipe_item_service.create_recipe_item(
            session,
            RecipeItemCreate(**RECIPE_ITEM_PAYLOAD),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_revalidates_changed_parent_and_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    item = make_recipe_item()
    exists_mock = AsyncMock(return_value=True)
    pair_mock = AsyncMock(return_value=False)
    save_mock = AsyncMock(return_value=item)
    monkeypatch.setattr(
        recipe_item_repository,
        "get_recipe_item",
        AsyncMock(return_value=item),
    )
    monkeypatch.setattr(recipe_item_repository, "menu_item_exists", exists_mock)
    monkeypatch.setattr(
        recipe_item_repository,
        "ingredient_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(recipe_item_repository, "combination_exists", pair_mock)
    monkeypatch.setattr(recipe_item_repository, "save_recipe_item", save_mock)

    result = await recipe_item_service.update_recipe_item(
        session,
        1,
        RecipeItemUpdate(menu_item_id=11),
    )

    assert result.menu_item_id == 11
    exists_mock.assert_awaited_once_with(session, 11)
    pair_mock.assert_awaited_once_with(
        session,
        11,
        20,
        exclude_recipe_item_id=1,
    )
    assert transaction.exc_type is None


async def test_service_update_rejects_duplicate_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    item = make_recipe_item()
    monkeypatch.setattr(
        recipe_item_repository,
        "get_recipe_item",
        AsyncMock(return_value=item),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "ingredient_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "combination_exists",
        AsyncMock(return_value=True),
    )
    save_mock = AsyncMock()
    monkeypatch.setattr(recipe_item_repository, "save_recipe_item", save_mock)

    with pytest.raises(recipe_item_service.RecipeItemConflictError):
        await recipe_item_service.update_recipe_item(
            session,
            1,
            RecipeItemUpdate(ingredient_id=21),
        )

    save_mock.assert_not_awaited()
    assert transaction.exc_type is recipe_item_service.RecipeItemConflictError


async def test_service_delete_only_deletes_recipe_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    item = make_recipe_item()
    delete_mock = AsyncMock()
    monkeypatch.setattr(
        recipe_item_repository,
        "get_recipe_item",
        AsyncMock(return_value=item),
    )
    monkeypatch.setattr(
        recipe_item_repository,
        "delete_recipe_item",
        delete_mock,
    )

    await recipe_item_service.delete_recipe_item(session, 1)

    delete_mock.assert_awaited_once_with(session, item)
    assert transaction.exc_type is None
