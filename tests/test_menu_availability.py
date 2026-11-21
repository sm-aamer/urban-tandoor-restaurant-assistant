from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.main import app
from app.models import MenuAvailability
from app.repositories import menu_availability as menu_availability_repository
from app.schemas.menu_availability import (
    MenuAvailabilityCreate,
    MenuAvailabilityUpdate,
)
from app.services import menu_availability as menu_availability_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)
AVAILABILITY_PAYLOAD = {
    "branch_id": 1,
    "menu_item_id": 2,
    "is_available": True,
}


def make_availability(**overrides: object) -> MenuAvailability:
    return MenuAvailability(
        id=1,
        **(
            AVAILABILITY_PAYLOAD
            | {"created_at": NOW, "updated_at": NOW}
            | overrides
        ),
    )


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


@pytest.mark.parametrize(
    "filter_value,expected",
    [("true", True), ("false", False), ("null", None)],
)
async def test_list_filters_availability_values(
    monkeypatch: pytest.MonkeyPatch,
    filter_value: str,
    expected: bool | None,
) -> None:
    list_mock = AsyncMock(return_value=([make_availability(is_available=expected)], 1))
    monkeypatch.setattr(menu_availability_service, "list_menu_availability", list_mock)

    response = await request(
        "GET",
        f"/api/v1/menu-availability?is_available={filter_value}",
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["is_available"] is expected
    assert list_mock.await_args.kwargs["is_available"] is expected
    assert list_mock.await_args.kwargs["filter_is_available"] is True


async def test_list_menu_availability_returns_page_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_availability()], 1))
    monkeypatch.setattr(menu_availability_service, "list_menu_availability", list_mock)

    response = await request(
        "GET",
        "/api/v1/menu-availability?limit=5&offset=2&branch_id=1"
        "&menu_item_id=2&is_available=false",
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 2
    assert list_mock.await_args.kwargs == {
        "limit": 5,
        "offset": 2,
        "branch_id": 1,
        "menu_item_id": 2,
        "is_available": False,
        "filter_is_available": True,
    }


async def test_repository_list_filters_null_and_orders_by_id() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalars.return_value.all.return_value = [make_availability(is_available=None)]
    session.execute.return_value = result
    session.scalar.return_value = 1

    records, total = await menu_availability_repository.list_menu_availability(
        session,
        limit=10,
        offset=20,
        branch_id=1,
        menu_item_id=2,
        is_available=None,
        filter_is_available=True,
    )

    compiled = session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert "menu_availability.branch_id =" in sql
    assert "menu_availability.menu_item_id =" in sql
    assert "menu_availability.is_available IS NULL" in sql
    assert "ORDER BY menu_availability.id" in sql
    assert "LIMIT" in sql and "OFFSET" in sql
    assert compiled.params["param_1"] == 10
    assert compiled.params["param_2"] == 20
    assert records[0].is_available is None
    assert total == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "branch_id=0",
        "menu_item_id=0",
        "is_available=yes",
    ],
)
async def test_list_menu_availability_rejects_invalid_query(query: str) -> None:
    response = await request("GET", f"/api/v1/menu-availability?{query}")

    assert response.status_code == 422


async def test_list_without_is_available_filter_does_not_filter_nulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_availability(is_available=None)], 1))
    monkeypatch.setattr(menu_availability_service, "list_menu_availability", list_mock)

    response = await request("GET", "/api/v1/menu-availability")

    assert response.status_code == 200
    assert response.json()["items"][0]["is_available"] is None
    assert list_mock.await_args.kwargs["filter_is_available"] is False


async def test_get_menu_availability_returns_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_availability_service,
        "get_menu_availability",
        AsyncMock(return_value=make_availability(is_available=None)),
    )

    response = await request("GET", "/api/v1/menu-availability/1")

    assert response.status_code == 200
    assert response.json()["is_available"] is None


async def test_get_menu_availability_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_availability_service,
        "get_menu_availability",
        AsyncMock(side_effect=menu_availability_service.MenuAvailabilityNotFoundError),
    )

    response = await request("GET", "/api/v1/menu-availability/999")

    assert response.status_code == 404


async def test_create_menu_availability_returns_201_preserving_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_mock = AsyncMock(
        return_value=make_availability(is_available=None),
    )
    monkeypatch.setattr(
        menu_availability_service,
        "create_menu_availability",
        create_mock,
    )

    response = await request(
        "POST",
        "/api/v1/menu-availability",
        json=AVAILABILITY_PAYLOAD | {"is_available": None},
    )

    assert response.status_code == 201
    assert response.json()["is_available"] is None
    assert isinstance(create_mock.await_args.args[1], MenuAvailabilityCreate)
    assert create_mock.await_args.args[1].is_available is None


@pytest.mark.parametrize(
    "error,detail,status_code",
    [
        (
            menu_availability_service.BranchNotFoundError,
            "Branch not found.",
            422,
        ),
        (
            menu_availability_service.MenuItemNotFoundError,
            "Menu item not found.",
            422,
        ),
        (
            menu_availability_service.MenuAvailabilityConflictError,
            "Availability already exists for this branch and menu item.",
            409,
        ),
    ],
)
async def test_create_maps_missing_parents_and_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    detail: str,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        menu_availability_service,
        "create_menu_availability",
        AsyncMock(side_effect=error),
    )

    response = await request(
        "POST",
        "/api/v1/menu-availability",
        json=AVAILABILITY_PAYLOAD,
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    "payload",
    [
        {"branch_id": 1},
        AVAILABILITY_PAYLOAD | {"id": 99},
        AVAILABILITY_PAYLOAD | {"created_at": NOW.isoformat()},
        AVAILABILITY_PAYLOAD | {"branch_id": 0},
    ],
)
async def test_create_rejects_invalid_payload(payload: dict[str, object]) -> None:
    response = await request(
        "POST",
        "/api/v1/menu-availability",
        json=payload,
    )

    assert response.status_code == 422


async def test_update_changes_only_supplied_field_and_preserves_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_availability(is_available=None))
    monkeypatch.setattr(
        menu_availability_service,
        "update_menu_availability",
        update_mock,
    )

    response = await request(
        "PATCH",
        "/api/v1/menu-availability/1",
        json={"is_available": None},
    )

    assert response.status_code == 200
    assert response.json()["is_available"] is None
    patch_schema = update_mock.await_args.args[2]
    assert patch_schema.model_fields_set == {"is_available"}
    assert patch_schema.model_dump(exclude_unset=True) == {"is_available": None}


@pytest.mark.parametrize(
    "error,status_code",
    [
        (menu_availability_service.MenuAvailabilityNotFoundError, 404),
        (menu_availability_service.BranchNotFoundError, 422),
        (menu_availability_service.MenuItemNotFoundError, 422),
        (menu_availability_service.MenuAvailabilityConflictError, 409),
    ],
)
async def test_update_maps_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    status_code: int,
) -> None:
    monkeypatch.setattr(
        menu_availability_service,
        "update_menu_availability",
        AsyncMock(side_effect=error),
    )

    response = await request(
        "PATCH",
        "/api/v1/menu-availability/1",
        json={"branch_id": 2},
    )

    assert response.status_code == status_code


@pytest.mark.parametrize(
    "payload",
    [{}, {"branch_id": None}, {"menu_item_id": None}, {"id": 2}],
)
async def test_update_rejects_empty_or_invalid_patch(
    payload: dict[str, object],
) -> None:
    response = await request(
        "PATCH",
        "/api/v1/menu-availability/1",
        json=payload,
    )

    assert response.status_code == 422


async def test_delete_removes_availability_relationship(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        menu_availability_service,
        "delete_menu_availability",
        delete_mock,
    )

    response = await request("DELETE", "/api/v1/menu-availability/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        menu_availability_service,
        "delete_menu_availability",
        AsyncMock(side_effect=menu_availability_service.MenuAvailabilityNotFoundError),
    )

    response = await request("DELETE", "/api/v1/menu-availability/999")

    assert response.status_code == 404


def test_menu_availability_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/menu-availability", "get"),
        ("/api/v1/menu-availability", "post"),
        ("/api/v1/menu-availability/{availability_id}", "get"),
        ("/api/v1/menu-availability/{availability_id}", "patch"),
        ("/api/v1/menu-availability/{availability_id}", "delete"),
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


async def test_service_create_validates_parents_and_combination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    branch_exists = AsyncMock(return_value=True)
    menu_item_exists = AsyncMock(return_value=True)
    pair_exists = AsyncMock(return_value=False)
    create_mock = AsyncMock(return_value=make_availability())
    monkeypatch.setattr(
        menu_availability_repository,
        "branch_exists",
        branch_exists,
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "menu_item_exists",
        menu_item_exists,
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "combination_exists",
        pair_exists,
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "create_menu_availability",
        create_mock,
    )

    record = await menu_availability_service.create_menu_availability(
        session,
        MenuAvailabilityCreate(**AVAILABILITY_PAYLOAD),
    )

    assert record.branch_id == 1
    branch_exists.assert_awaited_once_with(session, 1)
    menu_item_exists.assert_awaited_once_with(session, 2)
    pair_exists.assert_awaited_once_with(session, 1, 2)
    assert transaction.exc_type is None


@pytest.mark.parametrize(
    "missing_parent,error_type",
    [
        ("branch", menu_availability_service.BranchNotFoundError),
        ("menu_item", menu_availability_service.MenuItemNotFoundError),
    ],
)
async def test_service_create_rejects_missing_parent(
    monkeypatch: pytest.MonkeyPatch,
    missing_parent: str,
    error_type: type[Exception],
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        menu_availability_repository,
        "branch_exists",
        AsyncMock(return_value=missing_parent != "branch"),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "menu_item_exists",
        AsyncMock(return_value=missing_parent != "menu_item"),
    )
    create_mock = AsyncMock()
    monkeypatch.setattr(
        menu_availability_repository,
        "create_menu_availability",
        create_mock,
    )

    with pytest.raises(error_type):
        await menu_availability_service.create_menu_availability(
            session,
            MenuAvailabilityCreate(**AVAILABILITY_PAYLOAD),
        )

    create_mock.assert_not_awaited()
    assert transaction.exc_type is error_type


async def test_service_create_rejects_duplicate_combination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        menu_availability_repository,
        "branch_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "combination_exists",
        AsyncMock(return_value=True),
    )
    create_mock = AsyncMock()
    monkeypatch.setattr(
        menu_availability_repository,
        "create_menu_availability",
        create_mock,
    )

    with pytest.raises(menu_availability_service.MenuAvailabilityConflictError):
        await menu_availability_service.create_menu_availability(
            session,
            MenuAvailabilityCreate(**AVAILABILITY_PAYLOAD),
        )

    create_mock.assert_not_awaited()
    assert transaction.exc_type is menu_availability_service.MenuAvailabilityConflictError


async def test_service_create_maps_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        menu_availability_repository,
        "branch_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "combination_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "create_menu_availability",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(menu_availability_service.MenuAvailabilityConflictError) as error:
        await menu_availability_service.create_menu_availability(
            session,
            MenuAvailabilityCreate(**AVAILABILITY_PAYLOAD),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_revalidates_parents_and_unique_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    record = make_availability()
    branch_exists = AsyncMock(return_value=True)
    menu_exists = AsyncMock(return_value=True)
    pair_exists = AsyncMock(return_value=False)
    save_mock = AsyncMock(return_value=record)
    monkeypatch.setattr(
        menu_availability_repository,
        "get_menu_availability",
        AsyncMock(return_value=record),
    )
    monkeypatch.setattr(menu_availability_repository, "branch_exists", branch_exists)
    monkeypatch.setattr(menu_availability_repository, "menu_item_exists", menu_exists)
    monkeypatch.setattr(menu_availability_repository, "combination_exists", pair_exists)
    monkeypatch.setattr(
        menu_availability_repository,
        "save_menu_availability",
        save_mock,
    )

    result = await menu_availability_service.update_menu_availability(
        session,
        1,
        MenuAvailabilityUpdate(menu_item_id=3),
    )

    assert result.menu_item_id == 3
    branch_exists.assert_awaited_once_with(session, 1)
    menu_exists.assert_awaited_once_with(session, 3)
    pair_exists.assert_awaited_once_with(
        session,
        1,
        3,
        exclude_availability_id=1,
    )
    assert transaction.exc_type is None


async def test_service_update_preserves_explicit_null_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    record = make_availability()
    save_mock = AsyncMock(return_value=record)
    monkeypatch.setattr(
        menu_availability_repository,
        "get_menu_availability",
        AsyncMock(return_value=record),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "save_menu_availability",
        save_mock,
    )

    result = await menu_availability_service.update_menu_availability(
        session,
        1,
        MenuAvailabilityUpdate(is_available=None),
    )

    assert result.is_available is None
    save_mock.assert_awaited_once_with(session, record)
    assert transaction.exc_type is None


async def test_service_update_rejects_duplicate_combination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    record = make_availability()
    monkeypatch.setattr(
        menu_availability_repository,
        "get_menu_availability",
        AsyncMock(return_value=record),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "branch_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "combination_exists",
        AsyncMock(return_value=True),
    )
    save_mock = AsyncMock()
    monkeypatch.setattr(
        menu_availability_repository,
        "save_menu_availability",
        save_mock,
    )

    with pytest.raises(menu_availability_service.MenuAvailabilityConflictError):
        await menu_availability_service.update_menu_availability(
            session,
            1,
            MenuAvailabilityUpdate(branch_id=4),
        )

    save_mock.assert_not_awaited()
    assert transaction.exc_type is menu_availability_service.MenuAvailabilityConflictError


async def test_service_update_maps_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    record = make_availability()
    monkeypatch.setattr(
        menu_availability_repository,
        "get_menu_availability",
        AsyncMock(return_value=record),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "branch_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "menu_item_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "combination_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "save_menu_availability",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(menu_availability_service.MenuAvailabilityConflictError) as error:
        await menu_availability_service.update_menu_availability(
            session,
            1,
            MenuAvailabilityUpdate(menu_item_id=3),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_delete_only_deletes_availability_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    record = make_availability()
    delete_mock = AsyncMock()
    monkeypatch.setattr(
        menu_availability_repository,
        "get_menu_availability",
        AsyncMock(return_value=record),
    )
    monkeypatch.setattr(
        menu_availability_repository,
        "delete_menu_availability",
        delete_mock,
    )

    await menu_availability_service.delete_menu_availability(session, 1)

    delete_mock.assert_awaited_once_with(session, record)
    assert transaction.exc_type is None
