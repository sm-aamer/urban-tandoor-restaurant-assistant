from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.main import app
from app.models import Branch
from app.repositories import branch as branch_repository
from app.schemas.branch import BranchCreate, BranchUpdate
from app.services import branch as branch_service

NOW = datetime(2026, 1, 1, tzinfo=UTC)
BRANCH_PAYLOAD = {
    "branch_code": "UTG-KHI-003",
    "name": "North Nazimabad",
    "address": "Karachi",
    "table_count": 12,
    "seat_capacity": 48,
    "operating_hours": "24/7",
    "is_active": True,
}


def make_branch(**overrides: object) -> Branch:
    return Branch(
        id=1,
        **(BRANCH_PAYLOAD | {"created_at": NOW, "updated_at": NOW} | overrides),
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


async def test_list_branches_returns_page_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_mock = AsyncMock(return_value=([make_branch()], 1))
    monkeypatch.setattr(branch_service, "list_branches", list_mock)

    response = await request(
        "GET",
        "/api/v1/branches?limit=5&offset=2&is_active=false",
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 5
    assert response.json()["offset"] == 2
    list_mock.assert_awaited_once_with(
        list_mock.await_args.args[0],
        limit=5,
        offset=2,
        is_active=False,
    )


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1", "offset=100001"],
)
async def test_list_branches_rejects_out_of_range_pagination(query: str) -> None:
    response = await request("GET", f"/api/v1/branches?{query}")

    assert response.status_code == 422


async def test_get_branch_returns_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        branch_service,
        "get_branch",
        AsyncMock(return_value=make_branch()),
    )

    response = await request("GET", "/api/v1/branches/1")

    assert response.status_code == 200
    assert response.json()["branch_code"] == BRANCH_PAYLOAD["branch_code"]


async def test_get_branch_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        branch_service,
        "get_branch",
        AsyncMock(side_effect=branch_service.BranchNotFoundError),
    )

    response = await request("GET", "/api/v1/branches/999")

    assert response.status_code == 404


async def test_create_branch_returns_201(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_mock = AsyncMock(return_value=make_branch())
    monkeypatch.setattr(branch_service, "create_branch", create_mock)

    response = await request("POST", "/api/v1/branches", json=BRANCH_PAYLOAD)

    assert response.status_code == 201
    assert response.json()["branch_code"] == BRANCH_PAYLOAD["branch_code"]
    assert isinstance(create_mock.await_args.args[1], BranchCreate)


async def test_create_branch_maps_duplicate_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        branch_service,
        "create_branch",
        AsyncMock(side_effect=branch_service.BranchConflictError),
    )

    response = await request("POST", "/api/v1/branches", json=BRANCH_PAYLOAD)

    assert response.status_code == 409
    assert "branch code" in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Missing branch code"},
        BRANCH_PAYLOAD | {"id": 99},
        BRANCH_PAYLOAD | {"created_at": NOW.isoformat()},
        BRANCH_PAYLOAD | {"table_count": -1},
    ],
)
async def test_create_branch_rejects_invalid_input(payload: dict[str, object]) -> None:
    response = await request("POST", "/api/v1/branches", json=payload)

    assert response.status_code == 422


async def test_update_branch_returns_updated_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_mock = AsyncMock(return_value=make_branch(name="Updated"))
    monkeypatch.setattr(branch_service, "update_branch", update_mock)

    response = await request(
        "PATCH",
        "/api/v1/branches/1",
        json={"name": "Updated"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated"
    assert update_mock.await_args.args[2].model_dump(exclude_unset=True) == {
        "name": "Updated"
    }


async def test_update_branch_maps_not_found_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for error, expected_status in (
        (branch_service.BranchNotFoundError, 404),
        (branch_service.BranchConflictError, 409),
    ):
        monkeypatch.setattr(
            branch_service,
            "update_branch",
            AsyncMock(side_effect=error),
        )
        response = await request(
            "PATCH",
            "/api/v1/branches/1",
            json={"name": "Updated"},
        )
        assert response.status_code == expected_status


@pytest.mark.parametrize(
    "payload",
    [{}, {"branch_code": None}, {"is_active": None}, {"id": 2}, {"updated_at": "now"}],
)
async def test_update_branch_rejects_empty_null_and_server_fields(
    payload: dict[str, object],
) -> None:
    response = await request("PATCH", "/api/v1/branches/1", json=payload)

    assert response.status_code == 422


async def test_delete_branch_returns_empty_204(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(branch_service, "deactivate_branch", delete_mock)

    response = await request("DELETE", "/api/v1/branches/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_branch_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        branch_service,
        "deactivate_branch",
        AsyncMock(side_effect=branch_service.BranchNotFoundError),
    )

    response = await request("DELETE", "/api/v1/branches/999")

    assert response.status_code == 404


def test_branch_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]
    assert {
        ("/api/v1/branches", "get"),
        ("/api/v1/branches", "post"),
        ("/api/v1/branches/{branch_id}", "get"),
        ("/api/v1/branches/{branch_id}", "patch"),
        ("/api/v1/branches/{branch_id}", "delete"),
    } <= {
        (path, method)
        for path, operations in paths.items()
        for method in operations
    }


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


async def test_service_create_uses_explicit_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    created = make_branch()
    create_mock = AsyncMock(return_value=created)
    monkeypatch.setattr(branch_repository, "create_branch", create_mock)

    result = await branch_service.create_branch(
        session,
        BranchCreate(**BRANCH_PAYLOAD),
    )

    assert result.branch_code == created.branch_code
    assert transaction.exc_type is None
    assert create_mock.await_args.args[1].branch_code == "UTG-KHI-003"


async def test_service_create_sanitizes_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        branch_repository,
        "create_branch",
        AsyncMock(
            side_effect=IntegrityError("statement", {}, Exception("sensitive"))
        ),
    )

    with pytest.raises(branch_service.BranchConflictError) as error:
        await branch_service.create_branch(session, BranchCreate(**BRANCH_PAYLOAD))

    assert str(error.value) == ""
    assert transaction.exc_type is IntegrityError


async def test_service_update_changes_only_supplied_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    branch = make_branch()
    save_mock = AsyncMock(return_value=branch)
    monkeypatch.setattr(
        branch_repository,
        "get_branch",
        AsyncMock(return_value=branch),
    )
    monkeypatch.setattr(branch_repository, "save_branch", save_mock)

    result = await branch_service.update_branch(
        session,
        1,
        BranchUpdate(name="Updated"),
    )

    assert result.name == "Updated"
    assert result.branch_code == BRANCH_PAYLOAD["branch_code"]
    save_mock.assert_awaited_once_with(session, branch)
    assert transaction.exc_type is None


async def test_service_update_missing_branch_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    monkeypatch.setattr(
        branch_repository,
        "get_branch",
        AsyncMock(return_value=None),
    )

    with pytest.raises(branch_service.BranchNotFoundError):
        await branch_service.update_branch(session, 99, BranchUpdate(name="Updated"))

    assert transaction.exc_type is branch_service.BranchNotFoundError


async def test_service_delete_soft_deletes_without_session_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transaction = make_session()
    branch = make_branch()
    save_mock = AsyncMock(return_value=branch)
    monkeypatch.setattr(
        branch_repository,
        "get_branch",
        AsyncMock(return_value=branch),
    )
    monkeypatch.setattr(branch_repository, "save_branch", save_mock)

    await branch_service.deactivate_branch(session, 1)

    assert branch.is_active is False
    save_mock.assert_awaited_once_with(session, branch)
    session.delete.assert_not_awaited()
    assert transaction.exc_type is None
