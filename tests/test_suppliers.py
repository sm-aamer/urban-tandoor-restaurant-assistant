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
from app.models import Supplier
from app.repositories import supplier as supplier_repository
from app.schemas.supplier import SupplierCreate, SupplierUpdate
from app.services import supplier as supplier_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SUPPLIER_PAYLOAD = {
    "supplier_code": "SUP-TEST-1",
    "name": "Test Supplier",
    "supply_category": "Produce",
    "contact": "contact@example.test",
    "verification_status": "Pending",
    "is_active": True,
}


def make_supplier(**overrides: object) -> Supplier:
    return Supplier(
        id=1,
        **(
            SUPPLIER_PAYLOAD
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


async def test_list_suppliers_returns_page_and_both_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_supplier()], 1))
    monkeypatch.setattr(supplier_service, "list_suppliers", list_mock)

    response = await request(
        "GET",
        "/api/v1/suppliers?limit=5&offset=2&is_active=false&supply_category=Produce",
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 2
    assert list_mock.await_args.kwargs == {
        "limit": 5,
        "offset": 2,
        "is_active": False,
        "supply_category": "Produce",
    }


async def test_list_suppliers_preserves_null_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        supplier_service,
        "list_suppliers",
        AsyncMock(return_value=([make_supplier(is_active=None)], 1)),
    )

    response = await request("GET", "/api/v1/suppliers")

    assert response.status_code == 200
    assert response.json()["items"][0]["is_active"] is None


async def test_repository_list_applies_filters_order_and_pagination() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalars.return_value.all.return_value = [make_supplier()]
    session.execute.return_value = result
    session.scalar.return_value = 1

    suppliers, total = await supplier_repository.list_suppliers(
        session,
        limit=10,
        offset=20,
        is_active=False,
        supply_category="Produce",
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "supplier.is_active = false" in sql
    assert "supplier.supply_category = %(supply_category_1)s" in sql
    assert "ORDER BY supplier.supplier_code" in sql
    assert "LIMIT %(param_1)s" in sql
    assert "OFFSET %(param_2)s" in sql
    assert compiled.params["param_1"] == 10
    assert compiled.params["param_2"] == 20
    assert compiled.params["supply_category_1"] == "Produce"
    assert suppliers[0].supplier_code == SUPPLIER_PAYLOAD["supplier_code"]
    assert total == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "supply_category=",
        f"supply_category={'x' * 121}",
    ],
)
async def test_list_suppliers_rejects_invalid_query_parameters(query: str) -> None:
    response = await request("GET", f"/api/v1/suppliers?{query}")

    assert response.status_code == 422


async def test_get_supplier_returns_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        supplier_service,
        "get_supplier",
        AsyncMock(return_value=make_supplier(is_active=None)),
    )

    response = await request("GET", "/api/v1/suppliers/1")

    assert response.status_code == 200
    assert response.json()["is_active"] is None


async def test_get_supplier_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        supplier_service,
        "get_supplier",
        AsyncMock(side_effect=supplier_service.SupplierNotFoundError),
    )

    response = await request("GET", "/api/v1/suppliers/999")

    assert response.status_code == 404


async def test_create_supplier_returns_201_and_preserves_null_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_mock = AsyncMock(return_value=make_supplier(is_active=None))
    monkeypatch.setattr(supplier_service, "create_supplier", create_mock)

    payload = SUPPLIER_PAYLOAD | {"is_active": None}
    response = await request("POST", "/api/v1/suppliers", json=payload)

    assert response.status_code == 201
    assert response.json()["is_active"] is None
    assert isinstance(create_mock.await_args.args[1], SupplierCreate)


async def test_create_supplier_maps_duplicate_code_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        supplier_service,
        "create_supplier",
        AsyncMock(side_effect=supplier_service.SupplierConflictError),
    )

    response = await request(
        "POST",
        "/api/v1/suppliers",
        json=SUPPLIER_PAYLOAD,
    )

    assert response.status_code == 409
    assert "supplier code" in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Missing supplier code"},
        SUPPLIER_PAYLOAD | {"id": 99},
        SUPPLIER_PAYLOAD | {"created_at": NOW.isoformat()},
        SUPPLIER_PAYLOAD | {"supplier_code": " "},
    ],
)
async def test_create_supplier_rejects_invalid_payload(
    payload: dict[str, object],
) -> None:
    response = await request("POST", "/api/v1/suppliers", json=payload)

    assert response.status_code == 422


async def test_update_supplier_changes_only_supplied_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_supplier(name="Updated"))
    monkeypatch.setattr(supplier_service, "update_supplier", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/suppliers/1",
        json={"name": "Updated"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated"
    assert update_mock.await_args.args[2].model_dump(exclude_unset=True) == {
        "name": "Updated"
    }


async def test_update_supplier_can_set_active_to_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_supplier(is_active=None))
    monkeypatch.setattr(supplier_service, "update_supplier", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/suppliers/1",
        json={"is_active": None},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is None
    assert update_mock.await_args.args[2].is_active is None


async def test_update_supplier_maps_missing_and_integrity_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for error, expected_status in (
        (supplier_service.SupplierNotFoundError, 404),
        (supplier_service.SupplierConflictError, 409),
    ):
        monkeypatch.setattr(
            supplier_service,
            "update_supplier",
            AsyncMock(side_effect=error),
        )
        response = await request(
            "PATCH",
            "/api/v1/suppliers/1",
            json={"supplier_code": "SUP-UPDATED"},
        )
        assert response.status_code == expected_status


@pytest.mark.parametrize(
    "payload",
    [{}, {"supplier_code": None}, {"name": None}, {"id": 2}, {"updated_at": "now"}],
)
async def test_update_supplier_rejects_invalid_patch(
    payload: dict[str, object],
) -> None:
    response = await request("PATCH", "/api/v1/suppliers/1", json=payload)

    assert response.status_code == 422


async def test_delete_supplier_soft_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(supplier_service, "deactivate_supplier", delete_mock)

    response = await request("DELETE", "/api/v1/suppliers/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_supplier_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        supplier_service,
        "deactivate_supplier",
        AsyncMock(side_effect=supplier_service.SupplierNotFoundError),
    )

    response = await request("DELETE", "/api/v1/suppliers/999")

    assert response.status_code == 404


def test_supplier_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/suppliers", "get"),
        ("/api/v1/suppliers", "post"),
        ("/api/v1/suppliers/{supplier_id}", "get"),
        ("/api/v1/suppliers/{supplier_id}", "patch"),
        ("/api/v1/suppliers/{supplier_id}", "delete"),
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


async def test_service_create_uses_transaction_and_keeps_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    created = make_supplier(is_active=None)
    create_mock = AsyncMock(return_value=created)
    monkeypatch.setattr(supplier_repository, "create_supplier", create_mock)

    result = await supplier_service.create_supplier(
        session,
        SupplierCreate(**(SUPPLIER_PAYLOAD | {"is_active": None})),
    )

    assert result.supplier_code == created.supplier_code
    assert result.is_active is None
    assert create_mock.await_args.args[1].is_active is None
    assert transaction.exc_type is None


async def test_service_create_converts_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        supplier_repository,
        "create_supplier",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(supplier_service.SupplierConflictError) as error:
        await supplier_service.create_supplier(
            session,
            SupplierCreate(**SUPPLIER_PAYLOAD),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_can_preserve_or_clear_nullable_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    supplier = make_supplier(is_active=None)
    save_mock = AsyncMock(return_value=supplier)
    monkeypatch.setattr(
        supplier_repository,
        "get_supplier",
        AsyncMock(return_value=supplier),
    )
    monkeypatch.setattr(supplier_repository, "save_supplier", save_mock)

    result = await supplier_service.update_supplier(
        session,
        1,
        SupplierUpdate(contact="new-contact"),
    )

    assert result.is_active is None
    assert result.contact == "new-contact"
    save_mock.assert_awaited_once_with(session, supplier)
    assert transaction.exc_type is None


async def test_service_update_converts_integrity_error_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    supplier = make_supplier()
    monkeypatch.setattr(
        supplier_repository,
        "get_supplier",
        AsyncMock(return_value=supplier),
    )
    monkeypatch.setattr(
        supplier_repository,
        "save_supplier",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(supplier_service.SupplierConflictError) as error:
        await supplier_service.update_supplier(
            session,
            1,
            SupplierUpdate(supplier_code="DUPLICATE"),
        )

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_not_found_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        supplier_repository,
        "get_supplier",
        AsyncMock(return_value=None),
    )

    with pytest.raises(supplier_service.SupplierNotFoundError):
        await supplier_service.update_supplier(
            session,
            999,
            SupplierUpdate(name="Updated"),
        )

    assert transaction.exc_type is supplier_service.SupplierNotFoundError


async def test_service_soft_delete_sets_false_without_deleting_related_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    supplier = make_supplier(is_active=None)
    save_mock = AsyncMock(return_value=supplier)
    monkeypatch.setattr(
        supplier_repository,
        "get_supplier",
        AsyncMock(return_value=supplier),
    )
    monkeypatch.setattr(supplier_repository, "save_supplier", save_mock)

    await supplier_service.deactivate_supplier(session, 1)

    assert supplier.is_active is False
    save_mock.assert_awaited_once_with(session, supplier)
    session.delete.assert_not_awaited()
    assert transaction.exc_type is None
