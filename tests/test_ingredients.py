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
from app.models import Ingredient
from app.repositories import ingredient as ingredient_repository
from app.schemas.ingredient import IngredientCreate, IngredientUpdate
from app.services import ingredient as ingredient_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)
INGREDIENT_PAYLOAD = {
    "ingredient_code": "ING-TEST-1",
    "name": "Basmati Rice",
    "category": "Grains",
    "unit": "kg",
    "unit_cost_pkr": "123.45",
    "default_reorder_quantity": "5.125",
    "default_target_quantity": "10.250",
    "supplier_id": 7,
    "is_active": True,
}


def make_ingredient(**overrides: object) -> Ingredient:
    values = INGREDIENT_PAYLOAD | {
        "unit_cost_pkr": Decimal("123.45"),
        "default_reorder_quantity": Decimal("5.125"),
        "default_target_quantity": Decimal("10.250"),
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides
    return Ingredient(id=1, **values)


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


async def test_list_ingredients_returns_page_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_ingredient()], 1))
    monkeypatch.setattr(ingredient_service, "list_ingredients", list_mock)

    response = await request(
        "GET",
        "/api/v1/ingredients?limit=5&offset=2&is_active=false"
        "&category=Grains&supplier_id=7",
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 2
    assert list_mock.await_args.kwargs == {
        "limit": 5,
        "offset": 2,
        "is_active": False,
        "category": "Grains",
        "supplier_id": 7,
    }


async def test_repository_list_applies_filters_order_and_pagination() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalars.return_value.all.return_value = [make_ingredient()]
    session.execute.return_value = result
    session.scalar.return_value = 1

    ingredients, total = await ingredient_repository.list_ingredients(
        session,
        limit=10,
        offset=20,
        is_active=False,
        category="Grains",
        supplier_id=7,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ingredient.is_active = false" in sql
    assert "ingredient.category =" in sql
    assert "ingredient.supplier_id =" in sql
    assert "ORDER BY ingredient.ingredient_code" in sql
    assert "LIMIT" in sql and "OFFSET" in sql
    assert compiled.params["param_1"] == 10
    assert compiled.params["param_2"] == 20
    assert ingredients[0].ingredient_code == INGREDIENT_PAYLOAD["ingredient_code"]
    assert total == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "category=",
        "supplier_id=0",
    ],
)
async def test_list_ingredients_rejects_invalid_query(query: str) -> None:
    response = await request("GET", f"/api/v1/ingredients?{query}")

    assert response.status_code == 422


async def test_get_ingredient_returns_ingredient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "get_ingredient",
        AsyncMock(return_value=make_ingredient()),
    )

    response = await request("GET", "/api/v1/ingredients/1")

    assert response.status_code == 200
    assert response.json()["ingredient_code"] == INGREDIENT_PAYLOAD["ingredient_code"]
    assert response.json()["unit_cost_pkr"] == "123.45"
    assert response.json()["default_reorder_quantity"] == "5.125"


async def test_get_ingredient_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "get_ingredient",
        AsyncMock(side_effect=ingredient_service.IngredientNotFoundError),
    )

    response = await request("GET", "/api/v1/ingredients/999")

    assert response.status_code == 404


async def test_create_ingredient_returns_201_preserving_decimal_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_mock = AsyncMock(return_value=make_ingredient())
    monkeypatch.setattr(ingredient_service, "create_ingredient", create_mock)

    response = await request(
        "POST",
        "/api/v1/ingredients",
        json=INGREDIENT_PAYLOAD,
    )

    assert response.status_code == 201
    assert response.json()["unit_cost_pkr"] == "123.45"
    assert response.json()["default_reorder_quantity"] == "5.125"
    assert response.json()["default_target_quantity"] == "10.250"
    assert isinstance(create_mock.await_args.args[1], IngredientCreate)
    assert create_mock.await_args.args[1].unit_cost_pkr == Decimal("123.45")
    assert create_mock.await_args.args[1].default_reorder_quantity == Decimal("5.125")


async def test_create_ingredient_maps_duplicate_code_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "create_ingredient",
        AsyncMock(side_effect=ingredient_service.IngredientConflictError),
    )

    response = await request(
        "POST",
        "/api/v1/ingredients",
        json=INGREDIENT_PAYLOAD,
    )

    assert response.status_code == 409


async def test_create_ingredient_returns_422_for_missing_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "create_ingredient",
        AsyncMock(side_effect=ingredient_service.SupplierNotFoundError),
    )

    response = await request(
        "POST",
        "/api/v1/ingredients",
        json=INGREDIENT_PAYLOAD,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Supplier not found."


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Missing code"},
        INGREDIENT_PAYLOAD | {"id": 99},
        INGREDIENT_PAYLOAD | {"created_at": NOW.isoformat()},
        INGREDIENT_PAYLOAD | {"unit_cost_pkr": "1.239"},
        INGREDIENT_PAYLOAD | {"default_reorder_quantity": "1.1234"},
        INGREDIENT_PAYLOAD | {"unit_cost_pkr": "-1"},
    ],
)
async def test_create_ingredient_rejects_invalid_payload(
    payload: dict[str, object],
) -> None:
    response = await request("POST", "/api/v1/ingredients", json=payload)

    assert response.status_code == 422


async def test_create_ingredient_allows_null_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingredient = make_ingredient(supplier_id=None)
    create_mock = AsyncMock(return_value=ingredient)
    monkeypatch.setattr(ingredient_service, "create_ingredient", create_mock)

    response = await request(
        "POST",
        "/api/v1/ingredients",
        json=INGREDIENT_PAYLOAD | {"supplier_id": None},
    )

    assert response.status_code == 201
    assert response.json()["supplier_id"] is None


async def test_update_ingredient_changes_only_supplied_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_ingredient(name="New name"))
    monkeypatch.setattr(ingredient_service, "update_ingredient", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/ingredients/1",
        json={"name": "New name"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New name"
    assert update_mock.await_args.args[2].model_dump(exclude_unset=True) == {
        "name": "New name"
    }


async def test_update_ingredient_can_clear_supplier_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_ingredient(supplier_id=None))
    monkeypatch.setattr(ingredient_service, "update_ingredient", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/ingredients/1",
        json={"supplier_id": None},
    )

    assert response.status_code == 200
    assert response.json()["supplier_id"] is None
    assert update_mock.await_args.args[2].model_fields_set == {"supplier_id"}


async def test_update_ingredient_maps_missing_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "update_ingredient",
        AsyncMock(side_effect=ingredient_service.SupplierNotFoundError),
    )

    response = await request(
        "PATCH",
        "/api/v1/ingredients/1",
        json={"supplier_id": 999},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (ingredient_service.IngredientNotFoundError, 404),
        (ingredient_service.IngredientConflictError, 409),
    ],
)
async def test_update_ingredient_maps_not_found_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    expected_status: int,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "update_ingredient",
        AsyncMock(side_effect=error),
    )

    response = await request(
        "PATCH",
        "/api/v1/ingredients/1",
        json={"ingredient_code": "ING-UPDATED"},
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "payload",
    [{}, {"ingredient_code": None}, {"name": None}, {"id": 2}, {"updated_at": "now"}],
)
async def test_update_ingredient_rejects_invalid_patch(
    payload: dict[str, object],
) -> None:
    response = await request("PATCH", "/api/v1/ingredients/1", json=payload)

    assert response.status_code == 422


async def test_delete_ingredient_soft_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ingredient_service, "deactivate_ingredient", delete_mock)

    response = await request("DELETE", "/api/v1/ingredients/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_ingredient_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingredient_service,
        "deactivate_ingredient",
        AsyncMock(side_effect=ingredient_service.IngredientNotFoundError),
    )

    response = await request("DELETE", "/api/v1/ingredients/999")

    assert response.status_code == 404


def test_ingredient_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/ingredients", "get"),
        ("/api/v1/ingredients", "post"),
        ("/api/v1/ingredients/{ingredient_id}", "get"),
        ("/api/v1/ingredients/{ingredient_id}", "patch"),
        ("/api/v1/ingredients/{ingredient_id}", "delete"),
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


async def test_service_create_validates_existing_supplier_and_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    supplier_exists = AsyncMock(return_value=True)
    create_mock = AsyncMock(return_value=make_ingredient())
    monkeypatch.setattr(
        ingredient_repository,
        "supplier_exists",
        supplier_exists,
    )
    monkeypatch.setattr(
        ingredient_repository,
        "create_ingredient",
        create_mock,
    )

    ingredient = await ingredient_service.create_ingredient(
        session,
        IngredientCreate(**INGREDIENT_PAYLOAD),
    )

    assert ingredient.ingredient_code == INGREDIENT_PAYLOAD["ingredient_code"]
    supplier_exists.assert_awaited_once_with(session, 7)
    assert create_mock.await_args.args[1].unit_cost_pkr == Decimal("123.45")
    assert create_mock.await_args.args[1].default_reorder_quantity == Decimal("5.125")
    assert transaction.exc_type is None


async def test_service_create_rejects_missing_supplier_without_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    supplier_exists = AsyncMock(return_value=False)
    create_mock = AsyncMock()
    monkeypatch.setattr(
        ingredient_repository,
        "supplier_exists",
        supplier_exists,
    )
    monkeypatch.setattr(
        ingredient_repository,
        "create_ingredient",
        create_mock,
    )

    with pytest.raises(ingredient_service.SupplierNotFoundError):
        await ingredient_service.create_ingredient(
            session,
            IngredientCreate(**INGREDIENT_PAYLOAD),
        )

    create_mock.assert_not_awaited()
    assert transaction.exc_type is ingredient_service.SupplierNotFoundError


async def test_service_create_maps_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        ingredient_repository,
        "supplier_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        ingredient_repository,
        "create_ingredient",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(ingredient_service.IngredientConflictError) as error:
        await ingredient_service.create_ingredient(
            session,
            IngredientCreate(**INGREDIENT_PAYLOAD),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_can_clear_supplier_and_preserve_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    ingredient = make_ingredient()
    save_mock = AsyncMock(return_value=ingredient)
    supplier_exists = AsyncMock()
    monkeypatch.setattr(
        ingredient_repository,
        "get_ingredient",
        AsyncMock(return_value=ingredient),
    )
    monkeypatch.setattr(ingredient_repository, "supplier_exists", supplier_exists)
    monkeypatch.setattr(ingredient_repository, "save_ingredient", save_mock)

    result = await ingredient_service.update_ingredient(
        session,
        1,
        IngredientUpdate(supplier_id=None),
    )

    assert result.supplier_id is None
    assert result.unit_cost_pkr == Decimal("123.45")
    supplier_exists.assert_not_awaited()
    save_mock.assert_awaited_once_with(session, ingredient)
    assert transaction.exc_type is None


async def test_service_update_rejects_missing_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    ingredient = make_ingredient()
    save_mock = AsyncMock()
    monkeypatch.setattr(
        ingredient_repository,
        "get_ingredient",
        AsyncMock(return_value=ingredient),
    )
    monkeypatch.setattr(
        ingredient_repository,
        "supplier_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(ingredient_repository, "save_ingredient", save_mock)

    with pytest.raises(ingredient_service.SupplierNotFoundError):
        await ingredient_service.update_ingredient(
            session,
            1,
            IngredientUpdate(supplier_id=999),
        )

    save_mock.assert_not_awaited()
    assert transaction.exc_type is ingredient_service.SupplierNotFoundError


async def test_service_update_maps_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    ingredient = make_ingredient()
    monkeypatch.setattr(
        ingredient_repository,
        "get_ingredient",
        AsyncMock(return_value=ingredient),
    )
    monkeypatch.setattr(
        ingredient_repository,
        "save_ingredient",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(ingredient_service.IngredientConflictError) as error:
        await ingredient_service.update_ingredient(
            session,
            1,
            IngredientUpdate(ingredient_code="DUPLICATE"),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_not_found_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        ingredient_repository,
        "get_ingredient",
        AsyncMock(return_value=None),
    )

    with pytest.raises(ingredient_service.IngredientNotFoundError):
        await ingredient_service.update_ingredient(
            session,
            999,
            IngredientUpdate(name="Updated"),
        )

    assert transaction.exc_type is ingredient_service.IngredientNotFoundError


async def test_service_soft_delete_does_not_delete_related_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    ingredient = make_ingredient()
    save_mock = AsyncMock(return_value=ingredient)
    monkeypatch.setattr(
        ingredient_repository,
        "get_ingredient",
        AsyncMock(return_value=ingredient),
    )
    monkeypatch.setattr(ingredient_repository, "save_ingredient", save_mock)

    await ingredient_service.deactivate_ingredient(session, 1)

    assert ingredient.is_active is False
    save_mock.assert_awaited_once_with(session, ingredient)
    session.delete.assert_not_awaited()
    assert transaction.exc_type is None
