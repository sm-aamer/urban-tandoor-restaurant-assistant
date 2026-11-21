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
from app.models import MenuItem
from app.repositories import menu_item as menu_item_repository
from app.schemas.menu_item import MenuItemCreate, MenuItemUpdate
from app.services import menu_item as menu_item_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)
MENU_ITEM_PAYLOAD = {
    "menu_code": "MENU-TEST-1",
    "name": "Chicken Biryani",
    "category": "Main Course",
    "description": "Aromatic rice dish",
    "price_pkr": "450.50",
    "is_active": True,
}


def make_menu_item(**overrides: object) -> MenuItem:
    values = MENU_ITEM_PAYLOAD | {
        "price_pkr": Decimal("450.50"),
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides
    return MenuItem(id=1, **values)


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


async def test_list_menu_items_returns_page_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_menu_item()], 1))
    monkeypatch.setattr(menu_item_service, "list_menu_items", list_mock)

    response = await request(
        "GET",
        "/api/v1/menu-items?limit=5&offset=2&is_active=false&category=Main%20Course",
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 2
    assert list_mock.await_args.kwargs == {
        "limit": 5,
        "offset": 2,
        "is_active": False,
        "category": "Main Course",
    }


async def test_repository_list_orders_and_paginates_menu_items() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalars.return_value.all.return_value = [make_menu_item()]
    session.execute.return_value = result
    session.scalar.return_value = 1

    menu_items, total = await menu_item_repository.list_menu_items(
        session,
        limit=10,
        offset=20,
        is_active=True,
        category="Main Course",
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "menu_item.is_active = true" in sql
    assert "menu_item.category =" in sql
    assert "ORDER BY menu_item.menu_code" in sql
    assert "LIMIT" in sql and "OFFSET" in sql
    assert compiled.params["param_1"] == 10
    assert compiled.params["param_2"] == 20
    assert menu_items[0].menu_code == MENU_ITEM_PAYLOAD["menu_code"]
    assert total == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "category=",
    ],
)
async def test_list_menu_items_rejects_invalid_query(query: str) -> None:
    response = await request("GET", f"/api/v1/menu-items?{query}")

    assert response.status_code == 422


async def test_get_menu_item_returns_item_and_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_item_service,
        "get_menu_item",
        AsyncMock(return_value=make_menu_item()),
    )

    response = await request("GET", "/api/v1/menu-items/1")

    assert response.status_code == 200
    assert response.json()["price_pkr"] == "450.50"
    assert response.json()["description"] == "Aromatic rice dish"


async def test_get_menu_item_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_item_service,
        "get_menu_item",
        AsyncMock(side_effect=menu_item_service.MenuItemNotFoundError),
    )

    response = await request("GET", "/api/v1/menu-items/999")

    assert response.status_code == 404


async def test_create_menu_item_returns_201_preserving_decimal_and_nulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_menu_item(category=None, description=None)
    create_mock = AsyncMock(return_value=item)
    monkeypatch.setattr(menu_item_service, "create_menu_item", create_mock)

    payload = MENU_ITEM_PAYLOAD | {"category": None, "description": None}
    response = await request("POST", "/api/v1/menu-items", json=payload)

    assert response.status_code == 201
    assert response.json()["price_pkr"] == "450.50"
    assert response.json()["category"] is None
    assert response.json()["description"] is None
    assert isinstance(create_mock.await_args.args[1], MenuItemCreate)
    assert create_mock.await_args.args[1].price_pkr == Decimal("450.50")


async def test_create_menu_item_maps_duplicate_code_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_item_service,
        "create_menu_item",
        AsyncMock(side_effect=menu_item_service.MenuItemConflictError),
    )

    response = await request(
        "POST",
        "/api/v1/menu-items",
        json=MENU_ITEM_PAYLOAD,
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Missing menu code"},
        MENU_ITEM_PAYLOAD | {"id": 99},
        MENU_ITEM_PAYLOAD | {"updated_at": NOW.isoformat()},
        MENU_ITEM_PAYLOAD | {"price_pkr": "1.239"},
        MENU_ITEM_PAYLOAD | {"price_pkr": "-1"},
    ],
)
async def test_create_menu_item_rejects_invalid_payload(
    payload: dict[str, object],
) -> None:
    response = await request("POST", "/api/v1/menu-items", json=payload)

    assert response.status_code == 422


async def test_create_menu_item_allows_null_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_menu_item(price_pkr=None)
    monkeypatch.setattr(
        menu_item_service,
        "create_menu_item",
        AsyncMock(return_value=item),
    )

    response = await request(
        "POST",
        "/api/v1/menu-items",
        json=MENU_ITEM_PAYLOAD | {"price_pkr": None},
    )

    assert response.status_code == 201
    assert response.json()["price_pkr"] is None


async def test_update_menu_item_changes_only_supplied_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_menu_item(name="Updated"))
    monkeypatch.setattr(menu_item_service, "update_menu_item", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/menu-items/1",
        json={"name": "Updated"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated"
    assert update_mock.await_args.args[2].model_dump(exclude_unset=True) == {
        "name": "Updated"
    }


async def test_update_menu_item_preserves_decimal_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(
        return_value=make_menu_item(price_pkr=Decimal("1250.75"))
    )
    monkeypatch.setattr(menu_item_service, "update_menu_item", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/menu-items/1",
        json={"price_pkr": "1250.75"},
    )

    assert response.status_code == 200
    assert response.json()["price_pkr"] == "1250.75"
    assert update_mock.await_args.args[2].price_pkr == Decimal("1250.75")


async def test_update_menu_item_can_clear_nullable_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(
        return_value=make_menu_item(category=None, description=None, price_pkr=None)
    )
    monkeypatch.setattr(menu_item_service, "update_menu_item", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/menu-items/1",
        json={"category": None, "description": None, "price_pkr": None},
    )

    assert response.status_code == 200
    assert response.json()["category"] is None
    assert response.json()["description"] is None
    assert response.json()["price_pkr"] is None


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (menu_item_service.MenuItemNotFoundError, 404),
        (menu_item_service.MenuItemConflictError, 409),
    ],
)
async def test_update_menu_item_maps_missing_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    expected_status: int,
) -> None:
    monkeypatch.setattr(
        menu_item_service,
        "update_menu_item",
        AsyncMock(side_effect=error),
    )

    response = await request(
        "PATCH",
        "/api/v1/menu-items/1",
        json={"menu_code": "MENU-UPDATED"},
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "payload",
    [{}, {"menu_code": None}, {"name": None}, {"id": 2}, {"created_at": "now"}],
)
async def test_update_menu_item_rejects_invalid_patch(
    payload: dict[str, object],
) -> None:
    response = await request("PATCH", "/api/v1/menu-items/1", json=payload)

    assert response.status_code == 422


async def test_delete_menu_item_soft_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(menu_item_service, "deactivate_menu_item", delete_mock)

    response = await request("DELETE", "/api/v1/menu-items/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_menu_item_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_item_service,
        "deactivate_menu_item",
        AsyncMock(side_effect=menu_item_service.MenuItemNotFoundError),
    )

    response = await request("DELETE", "/api/v1/menu-items/999")

    assert response.status_code == 404


def test_menu_item_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/menu-items", "get"),
        ("/api/v1/menu-items", "post"),
        ("/api/v1/menu-items/{menu_item_id}", "get"),
        ("/api/v1/menu-items/{menu_item_id}", "patch"),
        ("/api/v1/menu-items/{menu_item_id}", "delete"),
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


async def test_service_create_uses_explicit_transaction_and_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    create_mock = AsyncMock(return_value=make_menu_item())
    monkeypatch.setattr(
        menu_item_repository,
        "create_menu_item",
        create_mock,
    )

    item = await menu_item_service.create_menu_item(
        session,
        MenuItemCreate(**MENU_ITEM_PAYLOAD),
    )

    assert item.menu_code == MENU_ITEM_PAYLOAD["menu_code"]
    assert create_mock.await_args.args[1].price_pkr == Decimal("450.50")
    assert transaction.exc_type is None


async def test_service_create_converts_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        menu_item_repository,
        "create_menu_item",
        AsyncMock(side_effect=IntegrityError("statement", {}, Exception("sensitive"))),
    )

    with pytest.raises(menu_item_service.MenuItemConflictError) as error:
        await menu_item_service.create_menu_item(
            session,
            MenuItemCreate(**MENU_ITEM_PAYLOAD),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_can_clear_nullable_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    item = make_menu_item()
    save_mock = AsyncMock(return_value=item)
    monkeypatch.setattr(
        menu_item_repository,
        "get_menu_item",
        AsyncMock(return_value=item),
    )
    monkeypatch.setattr(menu_item_repository, "save_menu_item", save_mock)

    result = await menu_item_service.update_menu_item(
        session,
        1,
        MenuItemUpdate(category=None, description=None, price_pkr=None),
    )

    assert result.category is None
    assert result.description is None
    assert result.price_pkr is None
    save_mock.assert_awaited_once_with(session, item)
    assert transaction.exc_type is None


async def test_service_update_converts_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    item = make_menu_item()
    monkeypatch.setattr(
        menu_item_repository,
        "get_menu_item",
        AsyncMock(return_value=item),
    )
    monkeypatch.setattr(
        menu_item_repository,
        "save_menu_item",
        AsyncMock(side_effect=IntegrityError("statement", {}, Exception("sensitive"))),
    )

    with pytest.raises(menu_item_service.MenuItemConflictError) as error:
        await menu_item_service.update_menu_item(
            session,
            1,
            MenuItemUpdate(menu_code="DUPLICATE"),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_missing_item_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        menu_item_repository,
        "get_menu_item",
        AsyncMock(return_value=None),
    )

    with pytest.raises(menu_item_service.MenuItemNotFoundError):
        await menu_item_service.update_menu_item(
            session,
            999,
            MenuItemUpdate(name="Updated"),
        )

    assert transaction.exc_type is menu_item_service.MenuItemNotFoundError


async def test_service_soft_delete_never_deletes_item_or_relationships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    item = make_menu_item()
    save_mock = AsyncMock(return_value=item)
    monkeypatch.setattr(
        menu_item_repository,
        "get_menu_item",
        AsyncMock(return_value=item),
    )
    monkeypatch.setattr(menu_item_repository, "save_menu_item", save_mock)

    await menu_item_service.deactivate_menu_item(session, 1)

    assert item.is_active is False
    save_mock.assert_awaited_once_with(session, item)
    session.delete.assert_not_awaited()
    assert transaction.exc_type is None
