from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any, Self
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook
from sqlalchemy.dialects import postgresql

from app.models import (
    BranchStock,
    Ingredient,
    MenuAvailability,
    StockMovement,
)
from app.pipeline import importer
from app.pipeline.reader import (
    ImportIssue,
    SourceRow,
    WorkbookValidationError,
    read_workbook,
)

HEADERS = {
    "Branches": [
        "Branch_ID",
        "Branch_Name",
        "Address_Demo",
        "Tables",
        "Seats",
        "Hours",
        "Status",
    ],
    "Ingredients": [
        "Ingredient_ID",
        "Ingredient_Name",
        "Category",
        "Unit",
        "Unit_Cost_PKR",
        "Default_Reorder",
        "Default_Target",
        "Supplier_ID",
        "Status",
    ],
    "Branch_Stock": [
        "Branch_ID",
        "Ingredient_ID",
        "Ingredient_Name",
        "Category",
        "Unit",
        "Opening",
        "Received",
        "Consumed",
        "Wastage",
        "Adjustment",
        "Reserved",
        "On_Hand",
        "Reorder_Level",
        "Target_Stock",
        "Unit_Cost_PKR",
    ],
    "Recipes": [
        "Menu_ID",
        "Menu_Item",
        "Category",
        "Ingredient_ID",
        "Qty_Per_Portion",
    ],
    "Menu_Availability": [
        "Menu_ID",
        "Menu_Item",
        "Category",
        "Menu_Status",
    ],
    "Stock_Movements": [
        "Movement_ID",
        "Movement_Date",
        "Branch_ID",
        "Ingredient_ID",
        "Movement_Type",
        "Qty_Signed",
        "Unit",
        "Reference",
        "Reason",
        "Data_Type",
    ],
    "Suppliers": [
        "Supplier_ID",
        "Supplier_Name",
        "Supply_Category",
        "Contact",
        "Verification",
    ],
}


def _default_rows() -> dict[str, list[list[Any]]]:
    return {
        "Branches": [
            ["BR-1", "PECHS", "Karachi", 20, 80, "24/7", "Active"],
            ["BR-2", "Gulshan", "Karachi", 25, 100, "24/7", "Active"],
        ],
        "Ingredients": [
            ["ING-1", "Rice", "Grain", "kg", 4.25, 2, 10, "SUP-1", "Active"],
        ],
        "Branch_Stock": [
            [
                "BR-1",
                "ING-1",
                "Rice",
                "Grain",
                "kg",
                10,
                3,
                2,
                1,
                -0.5,
                1,
                "=F2+G2-H2-I2+J2",
                2,
                10,
                4.25,
            ],
        ],
        "Recipes": [["MENU-1", "Rice Bowl", "Main", "ING-1", 0.25]],
        "Menu_Availability": [["MENU-1", "Rice Bowl", "Main", "Active"]],
        "Stock_Movements": [
            [
                "MOV-1",
                "2026-03-01",
                "BR-1",
                "ING-1",
                "Receipt",
                3,
                "kg",
                "INV-1",
                "Restock",
                "Demo",
            ],
        ],
        "Suppliers": [["SUP-1", "Supplier One", "Grain", "contact", "Verified"]],
    }


def _write_workbook(
    path: Path,
    *,
    rows: dict[str, list[list[Any]]] | None = None,
    headers: dict[str, list[str]] | None = None,
) -> Path:
    sheet_rows = _default_rows() if rows is None else rows
    sheet_headers = HEADERS if headers is None else headers
    workbook = Workbook()
    workbook.active.title = "START_HERE"
    workbook.create_sheet("Dashboard")
    for sheet_name, columns in sheet_headers.items():
        worksheet = workbook.create_sheet(sheet_name)
        worksheet.append(columns)
        for row in sheet_rows[sheet_name]:
            worksheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def test_reader_parses_records_and_ignores_formula_cache(tmp_path: Path) -> None:
    workbook_path = _write_workbook(tmp_path / "source.xlsx")

    data = read_workbook(workbook_path)

    assert data.total_records == 10
    assert data.branch_stocks[0].values["quantity_on_hand"] == Decimal("9.500")
    assert data.ingredients[0].values["unit_cost_pkr"] == Decimal("4.25")
    assert len(data.menu_availability) == 2
    assert data.menu_items[0].values["is_active"] is True
    assert data.stock_movements[0].values["movement_date"].isoformat() == (
        "2026-03-01"
    )


def test_actual_workbook_has_all_423_normalized_records() -> None:
    project_root = Path(__file__).resolve().parents[1]
    data = read_workbook(
        project_root / "data" / "Urban_Tandoor_Two_Branch_Inventory_Dataset.xlsx"
    )

    assert data.source_rows == 359
    assert data.total_records == 423
    assert (
        len(data.branches),
        len(data.suppliers),
        len(data.ingredients),
        len(data.branch_stocks),
        len(data.menu_items),
        len(data.recipe_items),
        len(data.menu_availability),
        len(data.stock_movements),
    ) == (2, 7, 60, 120, 32, 130, 64, 8)


def test_reader_reports_missing_required_columns(tmp_path: Path) -> None:
    headers = {name: columns.copy() for name, columns in HEADERS.items()}
    headers["Branches"].remove("Hours")
    path = _write_workbook(tmp_path / "missing-column.xlsx", headers=headers)

    with pytest.raises(WorkbookValidationError, match="Hours"):
        read_workbook(path)


def test_reader_reports_missing_worksheet(tmp_path: Path) -> None:
    headers = {name: columns for name, columns in HEADERS.items() if name != "Suppliers"}
    path = _write_workbook(tmp_path / "missing-sheet.xlsx", headers=headers)

    with pytest.raises(WorkbookValidationError, match="Suppliers"):
        read_workbook(path)


def test_reader_reports_corrupt_workbook(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"not an xlsx archive")

    with pytest.raises(WorkbookValidationError, match="Unable to open"):
        read_workbook(path)


def test_reader_reports_invalid_required_fields_and_dates(tmp_path: Path) -> None:
    rows = _default_rows()
    rows["Branches"][0][6] = "Unknown"
    rows["Ingredients"][0][1] = None
    rows["Stock_Movements"][0][1] = "not-a-date"
    path = _write_workbook(tmp_path / "invalid.xlsx", rows=rows)

    with pytest.raises(WorkbookValidationError) as error:
        read_workbook(path)

    messages = str(error.value)
    assert "Branches row 2" in messages
    assert "Active or Inactive" in messages
    assert "Ingredient_Name is required" in messages
    assert "Stock_Movements row 2" in messages
    assert "ISO date" in messages


def test_reader_rejects_duplicate_ids_and_foreign_key_errors(
    tmp_path: Path,
) -> None:
    rows = _default_rows()
    rows["Branches"].append(rows["Branches"][0].copy())
    rows["Ingredients"][0][7] = "MISSING-SUPPLIER"
    path = _write_workbook(tmp_path / "duplicate-and-fk.xlsx", rows=rows)

    with pytest.raises(WorkbookValidationError) as error:
        read_workbook(path)

    assert "Duplicate key" in str(error.value)
    assert "unknown source ID 'MISSING-SUPPLIER'" in str(error.value)


def test_reader_rejects_invalid_decimal_precision(tmp_path: Path) -> None:
    rows = _default_rows()
    rows["Ingredients"][0][4] = "1.234"
    path = _write_workbook(tmp_path / "precision.xlsx", rows=rows)

    with pytest.raises(WorkbookValidationError, match="2 decimal places"):
        read_workbook(path)


def test_reader_rejects_movement_unit_conflict(tmp_path: Path) -> None:
    rows = _default_rows()
    rows["Stock_Movements"][0][6] = "litre"
    path = _write_workbook(tmp_path / "unit-conflict.xlsx", rows=rows)

    with pytest.raises(WorkbookValidationError, match="Unit conflicts"):
        read_workbook(path)


@pytest.mark.parametrize(
    ("opening", "consumed", "message"),
    [
        ("1", "4", "cannot be negative"),
        ("99999999999.999", "0", "Numeric(14, 3)"),
    ],
)
def test_reader_rejects_invalid_calculated_stock(
    tmp_path: Path,
    opening: str,
    consumed: str,
    message: str,
) -> None:
    rows = _default_rows()
    rows["Branch_Stock"][0][5] = opening
    rows["Branch_Stock"][0][7] = consumed
    path = _write_workbook(tmp_path / "invalid-stock.xlsx", rows=rows)

    with pytest.raises(WorkbookValidationError) as error:
        read_workbook(path)

    assert "Branch_Stock row 2" in str(error.value)
    assert message in str(error.value)
    assert error.value.source_rows == 8
    assert error.value.normalized_records == 10


class _FakeResult:
    rowcount = 1

    def all(self) -> list[tuple[int, str]]:
        return []


class _FakeTransaction:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            self.session.rollback_count += 1
        return False


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_count = 0
        self.statements: list[Any] = []
        self.added: list[Any] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    def add(self, instance: Any) -> None:
        instance.id = 42
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session


@pytest.mark.asyncio
async def test_upsert_emits_postgresql_conflict_update() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)

    await importer._upsert(
        session,
        BranchStock,
        [{"branch_id": 1, "ingredient_id": 2, "quantity_on_hand": Decimal(4)}],
        conflict_columns=("branch_id", "ingredient_id"),
        update_columns=("quantity_on_hand",),
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (branch_id, ingredient_id) DO UPDATE" in sql
    assert "quantity_on_hand = excluded.quantity_on_hand" in sql


@pytest.mark.asyncio
async def test_upsert_uses_stable_source_identifier() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)

    await importer._upsert(
        session,
        Ingredient,
        [{"ingredient_code": "ING-1", "name": "Rice"}],
        conflict_columns=("ingredient_code",),
        update_columns=("name",),
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (ingredient_code) DO UPDATE" in sql
    assert "name = excluded.name" in sql


@pytest.mark.asyncio
async def test_branch_stock_conflict_preserves_live_inventory() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)

    await importer._upsert(
        session,
        BranchStock,
        [
            {
                "branch_id": 1,
                "ingredient_id": 2,
                "quantity_on_hand": Decimal(12),
                "reserved_quantity": Decimal(3),
                "reorder_level": None,
                "target_stock": Decimal(20),
            }
        ],
        conflict_columns=("branch_id", "ingredient_id"),
        update_columns=("reorder_level", "target_stock", "updated_at"),
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "quantity_on_hand" not in sql.split("DO UPDATE SET", maxsplit=1)[1]
    assert "reserved_quantity" not in sql.split("DO UPDATE SET", maxsplit=1)[1]
    assert "coalesce(excluded.reorder_level, branch_stock.reorder_level)" in sql
    assert "coalesce(excluded.target_stock, branch_stock.target_stock)" in sql


@pytest.mark.asyncio
async def test_availability_conflict_is_ignored_without_setting_unknown_value() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=0)

    await importer._upsert(
        session,
        MenuAvailability,
        [{"branch_id": 1, "menu_item_id": 2}],
        conflict_columns=("branch_id", "menu_item_id"),
        update_columns=(),
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "DO NOTHING" in sql
    assert "is_available" not in sql


@pytest.mark.asyncio
async def test_movement_insert_never_updates_an_existing_ledger_row() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)

    await importer._upsert(
        session,
        StockMovement,
        [{"movement_code": "MOV-1"}],
        conflict_columns=("movement_code",),
        update_columns=(),
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (movement_code) DO NOTHING" in sql
    assert "DO UPDATE" not in sql


def _movement_source_row(
    *,
    quantity: Decimal = Decimal(3),
) -> SourceRow:
    return SourceRow(
        row_number=8,
        values={
            "movement_code": "MOV-1",
            "branch_code": "BR-1",
            "ingredient_code": "ING-1",
            "movement_type": "Receipt",
            "quantity": quantity,
            "movement_date": date(2026, 3, 1),
            "reference": "INV-1",
            "reason": "Restock",
            "data_type": "Demo",
        },
    )


def _mapped_movement_row(
    *,
    quantity: Decimal = Decimal(3),
) -> dict[str, Any]:
    return {
        "movement_code": "MOV-1",
        "branch_id": 10,
        "ingredient_id": 20,
        "supplier_id": None,
        "movement_type": "Receipt",
        "quantity": quantity,
        "movement_date": date(2026, 3, 1),
        "reference": "INV-1",
        "reason": "Restock",
        "data_type": "Demo",
    }


class _MappingResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _MappingResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


@pytest.mark.asyncio
async def test_exact_movement_replay_is_ignored() -> None:
    session = AsyncMock()
    session.execute.return_value = _MappingResult(
        [
            {
                "movement_code": "MOV-1",
                "branch_id": 10,
                "ingredient_id": 20,
                "movement_type": "Receipt",
                "quantity": Decimal(3),
                "movement_date": _movement_source_row().values["movement_date"],
                "reference": "INV-1",
                "reason": "Restock",
                "data_type": "Demo",
            }
        ]
    )

    accepted = await importer._filter_replayed_movements(
        session,
        [_mapped_movement_row()],
        [_movement_source_row()],
    )

    assert accepted == []


@pytest.mark.asyncio
async def test_conflicting_movement_replay_is_rejected() -> None:
    session = AsyncMock()
    session.execute.return_value = _MappingResult(
        [
            {
                "movement_code": "MOV-1",
                "branch_id": 10,
                "ingredient_id": 20,
                "movement_type": "Receipt",
                "quantity": Decimal(2),
                "movement_date": _movement_source_row().values["movement_date"],
                "reference": "INV-1",
                "reason": "Restock",
                "data_type": "Demo",
            }
        ]
    )

    with pytest.raises(
        importer.ImportConflictError,
        match="different ledger data",
    ) as error:
        await importer._filter_replayed_movements(
            session,
            [_mapped_movement_row()],
            [_movement_source_row()],
        )
    issue = error.value.issue
    assert issue.worksheet == "Stock_Movements"
    assert issue.row_number == 8


async def test_upsert_mapping_preserves_parsed_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = read_workbook(_write_workbook(tmp_path / "mapping.xlsx"))
    calls: list[tuple[type[Any], list[dict[str, Any]], dict[str, Any]]] = []
    id_map = {
        "Supplier": {"SUP-1": 1},
        "Branch": {"BR-1": 10, "BR-2": 11},
        "Ingredient": {"ING-1": 20},
        "MenuItem": {"MENU-1": 30},
    }

    async def capture_upsert(
        session: Any,
        model: type[Any],
        rows: list[dict[str, Any]],
        **kwargs: Any,
    ) -> int:
        calls.append((model, rows, kwargs))
        return len(rows)

    async def capture_id_map(
        session: Any,
        model: type[Any],
        id_column: str,
        source_ids: set[str],
    ) -> dict[str, int]:
        return {key: id_map[model.__name__][key] for key in source_ids}

    monkeypatch.setattr(
        importer,
        "_filter_replayed_movements",
        AsyncMock(side_effect=lambda session, rows, source_rows: rows),
    )
    monkeypatch.setattr(importer, "_upsert", capture_upsert)
    monkeypatch.setattr(importer, "_id_map", capture_id_map)
    successful = await importer._upsert_entities(AsyncMock(), data)

    by_model = {model.__name__: rows for model, rows, _ in calls}
    update_options = {
        model.__name__: options
        for model, _, options in calls
    }
    assert successful == data.total_records
    assert by_model["Supplier"][0]["supplier_code"] == "SUP-1"
    assert by_model["Supplier"][0]["supply_category"] == "Grain"
    assert by_model["Supplier"][0]["contact"] == "contact"
    assert by_model["Supplier"][0]["verification_status"] == "Verified"
    assert "is_active" not in by_model["Supplier"][0]
    assert by_model["Branch"][0]["branch_code"] == "BR-1"
    assert by_model["Branch"][0]["address"] == "Karachi"
    assert by_model["Branch"][0]["table_count"] == 20
    assert by_model["Branch"][0]["seat_capacity"] == 80
    assert by_model["Branch"][0]["operating_hours"] == "24/7"
    assert by_model["Branch"][0]["is_active"] is True
    assert by_model["Ingredient"][0]["ingredient_code"] == "ING-1"
    assert by_model["Ingredient"][0]["name"] == "Rice"
    assert by_model["Ingredient"][0]["category"] == "Grain"
    assert by_model["Ingredient"][0]["unit"] == "kg"
    assert by_model["Ingredient"][0]["unit_cost_pkr"] == Decimal("4.25")
    assert by_model["Ingredient"][0]["default_reorder_quantity"] == Decimal(2)
    assert by_model["Ingredient"][0]["default_target_quantity"] == Decimal(10)
    assert by_model["Ingredient"][0]["supplier_id"] == 1
    assert by_model["Ingredient"][0]["is_active"] is True
    assert by_model["BranchStock"][0]["quantity_on_hand"] == Decimal("9.500")
    assert by_model["BranchStock"][0]["reserved_quantity"] == Decimal(1)
    assert by_model["BranchStock"][0]["branch_id"] == 10
    assert by_model["BranchStock"][0]["ingredient_id"] == 20
    assert by_model["BranchStock"][0]["reorder_level"] == Decimal(2)
    assert by_model["BranchStock"][0]["target_stock"] == Decimal(10)
    assert set(update_options["BranchStock"]["update_columns"]) == {
        "reorder_level",
        "target_stock",
        "updated_at",
    }
    assert by_model["MenuItem"][0]["menu_code"] == "MENU-1"
    assert by_model["MenuItem"][0]["name"] == "Rice Bowl"
    assert by_model["MenuItem"][0]["category"] == "Main"
    assert by_model["MenuItem"][0]["is_active"] is True
    assert "description" not in by_model["MenuItem"][0]
    assert "price_pkr" not in by_model["MenuItem"][0]
    assert by_model["RecipeItem"][0]["menu_item_id"] == 30
    assert by_model["RecipeItem"][0]["ingredient_id"] == 20
    assert by_model["RecipeItem"][0]["quantity_per_portion"] == Decimal("0.25")
    assert len(by_model["MenuAvailability"]) == 2
    assert by_model["MenuAvailability"][0]["branch_id"] == 10
    assert by_model["MenuAvailability"][0]["menu_item_id"] == 30
    assert "is_available" not in by_model["MenuAvailability"][0]
    assert update_options["MenuAvailability"]["update_columns"] == ()
    assert by_model["StockMovement"][0]["movement_code"] == "MOV-1"
    assert by_model["StockMovement"][0]["branch_id"] == 10
    assert by_model["StockMovement"][0]["ingredient_id"] == 20
    assert by_model["StockMovement"][0]["movement_type"] == "Receipt"
    assert by_model["StockMovement"][0]["quantity"] == Decimal(3)
    assert by_model["StockMovement"][0]["movement_date"] == (
        _movement_source_row().values["movement_date"]
    )
    assert by_model["StockMovement"][0]["reference"] == "INV-1"
    assert by_model["StockMovement"][0]["reason"] == "Restock"
    assert by_model["StockMovement"][0]["data_type"] == "Demo"
    assert by_model["StockMovement"][0]["supplier_id"] is None
    assert data.ingredients[0].values["supplier_code"] == "SUP-1"


@pytest.mark.asyncio
async def test_import_tracks_success_without_database_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_workbook(tmp_path / "success.xlsx")
    session_factory = _FakeSessionFactory()
    monkeypatch.setattr(
        importer,
        "_upsert_entities",
        AsyncMock(return_value=7),
    )

    result = await importer.import_workbook(session_factory, path)

    assert result.status == "completed"
    assert result.source_rows == 8
    assert result.normalized_records == 10
    assert result.successful_records == 7
    assert result.rejected_records == 0
    assert session_factory.sessions[0].added[0].status == "running"
    assert len(session_factory.sessions) == 2
    batch_counts = session_factory.sessions[1].statements[0].compile().params
    summary = json.loads(batch_counts["error_summary"])
    assert batch_counts["total_records"] == result.normalized_records
    assert batch_counts["successful_records"] == result.successful_records
    assert batch_counts["failed_records"] == result.rejected_records
    assert summary == {
        "source_rows": result.source_rows,
        "normalized_records": result.normalized_records,
        "successful_records": result.successful_records,
        "rejected_records": result.rejected_records,
        "issues": [],
    }


@pytest.mark.asyncio
async def test_import_records_validation_failure_in_separate_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = ImportIssue("Branches", 2, "Branch_ID is required.")
    monkeypatch.setattr(
        importer,
        "read_workbook",
        lambda path: (_ for _ in ()).throw(
            WorkbookValidationError(
                [issue],
                source_rows=5,
                normalized_records=3,
            )
        ),
    )
    session_factory = _FakeSessionFactory()

    result = await importer.import_workbook(
        session_factory,
        tmp_path / "invalid.xlsx",
    )

    assert result.status == "failed"
    assert result.source_rows == 5
    assert result.normalized_records == 3
    assert result.rejected_records == 3
    assert result.issues == (issue,)
    assert len(session_factory.sessions) == 2
    assert session_factory.sessions[0].rollback_count == 0
    batch_counts = session_factory.sessions[1].statements[0].compile().params
    assert batch_counts["total_records"] == result.normalized_records
    assert batch_counts["successful_records"] == 0
    assert batch_counts["failed_records"] == result.rejected_records
    assert json.loads(batch_counts["error_summary"])["source_rows"] == 5


@pytest.mark.asyncio
async def test_import_rolls_back_entities_and_records_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_workbook(tmp_path / "rollback.xlsx")
    session_factory = _FakeSessionFactory()

    async def fail_after_partial_write(session: Any, data: Any) -> int:
        await session.execute("simulated partial entity write")
        raise RuntimeError("database failure")

    monkeypatch.setattr(importer, "_upsert_entities", fail_after_partial_write)
    result = await importer.import_workbook(session_factory, path)

    assert result.status == "failed"
    assert result.source_rows == 8
    assert result.normalized_records == 10
    assert result.rejected_records == 10
    assert session_factory.sessions[1].rollback_count == 1
    assert session_factory.sessions[1].statements == [
        "simulated partial entity write"
    ]
    assert len(session_factory.sessions) == 3
