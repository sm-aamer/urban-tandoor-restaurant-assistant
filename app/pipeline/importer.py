from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

from app.models import (
    Branch,
    BranchStock,
    ImportBatch,
    Ingredient,
    MenuAvailability,
    MenuItem,
    RecipeItem,
    StockMovement,
    Supplier,
)
from app.models.base import utc_now
from app.pipeline.reader import (
    ImportIssue,
    SourceRow,
    WorkbookData,
    WorkbookValidationError,
    read_workbook,
)

SessionFactory = async_sessionmaker[AsyncSession]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportResult:
    """Counts use source rows, normalized entities, successful writes, and rejects.

    ``normalized_records`` counts all mapped entities. ``successful_records``
    counts database rows inserted or updated (ignored idempotent replays do not
    count). ``rejected_records`` counts normalized entities rejected when the
    batch fails; validation failure rejects all candidate normalized entities.
    """

    batch_id: int
    status: str
    source_rows: int
    normalized_records: int
    successful_records: int
    rejected_records: int
    issues: tuple[ImportIssue, ...] = ()


class ImportConflictError(ValueError):
    def __init__(self, issue: ImportIssue) -> None:
        self.issue = issue
        super().__init__(str(issue))


async def _upsert(
    session: AsyncSession,
    model: type[SQLModel],
    rows: Sequence[dict[str, Any]],
    *,
    conflict_columns: tuple[str, ...],
    update_columns: tuple[str, ...],
) -> int:
    if not rows:
        return 0
    statement = postgresql_insert(model).values(list(rows))
    if update_columns:
        statement = statement.on_conflict_do_update(
            index_elements=[getattr(model, column) for column in conflict_columns],
            set_={
                column: (
                    func.coalesce(
                        getattr(statement.excluded, column),
                        getattr(model, column),
                    )
                    if model is BranchStock and column in {
                        "reorder_level",
                        "target_stock",
                    }
                    else getattr(statement.excluded, column)
                )
                for column in update_columns
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                getattr(model, column) for column in conflict_columns
            ]
        )
    result = await session.execute(statement)
    return max(0, result.rowcount or 0)


async def _id_map(
    session: AsyncSession,
    model: type[SQLModel],
    id_column: str,
    source_ids: set[str],
) -> dict[str, int]:
    if not source_ids:
        return {}
    source_column = getattr(model, id_column)
    result = await session.execute(
        select(model.id, source_column).where(source_column.in_(source_ids))
    )
    return {source_id: record_id for record_id, source_id in result.all()}


def _timestamped(
    values: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    return {**values, "created_at": now, "updated_at": now}


async def _filter_replayed_movements(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    source_rows: Sequence[SourceRow],
) -> list[dict[str, Any]]:
    if not rows:
        return []

    by_code = {row.values["movement_code"]: row for row in source_rows}
    existing_result = await session.execute(
        select(
            StockMovement.movement_code,
            StockMovement.branch_id,
            StockMovement.ingredient_id,
            StockMovement.movement_type,
            StockMovement.quantity,
            StockMovement.movement_date,
            StockMovement.reference,
            StockMovement.reason,
            StockMovement.data_type,
        ).where(
            StockMovement.movement_code.in_(
                [row["movement_code"] for row in rows]
            )
        )
    )
    existing_rows = existing_result.mappings().all()
    existing_by_code = {
        row["movement_code"]: row for row in existing_rows
    }

    source_fields = (
        "branch_id",
        "ingredient_id",
        "movement_type",
        "quantity",
        "movement_date",
        "reference",
        "reason",
        "data_type",
    )
    accepted: list[dict[str, Any]] = []
    for row in rows:
        existing = existing_by_code.get(row["movement_code"])
        if existing is None:
            accepted.append(row)
            continue
        if any(existing[field] != row[field] for field in source_fields):
            source_row = by_code[row["movement_code"]]
            raise ImportConflictError(
                ImportIssue(
                    "Stock_Movements",
                    source_row.row_number,
                    f"Movement_ID {row['movement_code']!r} already exists "
                    "with different ledger data.",
                )
            )
    return accepted


async def _upsert_entities(session: AsyncSession, data: WorkbookData) -> int:
    now = utc_now()
    successful_records = 0

    supplier_rows = [
        _timestamped(row.values, now=now)
        for row in data.suppliers
    ]
    successful_records += await _upsert(
        session,
        Supplier,
        supplier_rows,
        conflict_columns=("supplier_code",),
        update_columns=(
            "name",
            "supply_category",
            "contact",
            "verification_status",
            "updated_at",
        ),
    )

    branch_rows = [
        _timestamped(row.values, now=now)
        for row in data.branches
    ]
    successful_records += await _upsert(
        session,
        Branch,
        branch_rows,
        conflict_columns=("branch_code",),
        update_columns=(
            "name",
            "address",
            "table_count",
            "seat_capacity",
            "operating_hours",
            "is_active",
            "updated_at",
        ),
    )

    supplier_ids = await _id_map(
        session,
        Supplier,
        "supplier_code",
        {row.values["supplier_code"] for row in data.suppliers},
    )
    ingredient_rows = [
        _timestamped(
            {
                **{
                    key: value
                    for key, value in row.values.items()
                    if key != "supplier_code"
                },
                "supplier_id": supplier_ids[row.values["supplier_code"]],
            },
            now=now,
        )
        for row in data.ingredients
    ]
    successful_records += await _upsert(
        session,
        Ingredient,
        ingredient_rows,
        conflict_columns=("ingredient_code",),
        update_columns=(
            "name",
            "category",
            "unit",
            "unit_cost_pkr",
            "default_reorder_quantity",
            "default_target_quantity",
            "supplier_id",
            "is_active",
            "updated_at",
        ),
    )

    branch_ids = await _id_map(
        session,
        Branch,
        "branch_code",
        {row.values["branch_code"] for row in data.branches},
    )
    ingredient_ids = await _id_map(
        session,
        Ingredient,
        "ingredient_code",
        {row.values["ingredient_code"] for row in data.ingredients},
    )
    branch_stock_rows = [
        _timestamped(
            {
                "quantity_on_hand": row.values["quantity_on_hand"],
                "reserved_quantity": row.values["reserved_quantity"],
                "reorder_level": row.values["reorder_level"],
                "target_stock": row.values["target_stock"],
                "branch_id": branch_ids[row.values["branch_code"]],
                "ingredient_id": ingredient_ids[row.values["ingredient_code"]],
            },
            now=now,
        )
        for row in data.branch_stocks
    ]
    successful_records += await _upsert(
        session,
        BranchStock,
        branch_stock_rows,
        conflict_columns=("branch_id", "ingredient_id"),
        update_columns=("reorder_level", "target_stock", "updated_at"),
    )

    # Existing operational stock and reservations are preserved. Workbook
    # reorder/target values update only when supplied; Ingredient.unit_cost_pkr
    # is maintained from Ingredients, while Branch_Stock cost is validation-only.

    menu_rows = [
        _timestamped(row.values, now=now)
        for row in data.menu_items
    ]
    successful_records += await _upsert(
        session,
        MenuItem,
        menu_rows,
        conflict_columns=("menu_code",),
        update_columns=("name", "category", "is_active", "updated_at"),
    )
    menu_ids = await _id_map(
        session,
        MenuItem,
        "menu_code",
        {row.values["menu_code"] for row in data.menu_items},
    )

    recipe_rows = [
        _timestamped(
            {
                "menu_item_id": menu_ids[row.values["menu_code"]],
                "ingredient_id": ingredient_ids[row.values["ingredient_code"]],
                "quantity_per_portion": row.values["quantity_per_portion"],
            },
            now=now,
        )
        for row in data.recipe_items
    ]
    successful_records += await _upsert(
        session,
        RecipeItem,
        recipe_rows,
        conflict_columns=("menu_item_id", "ingredient_id"),
        update_columns=("quantity_per_portion", "updated_at"),
    )

    availability_rows = [
        _timestamped(
            {
                "branch_id": branch_ids[row.values["branch_code"]],
                "menu_item_id": menu_ids[row.values["menu_code"]],
            },
            now=now,
        )
        for row in data.menu_availability
    ]
    successful_records += await _upsert(
        session,
        MenuAvailability,
        availability_rows,
        conflict_columns=("branch_id", "menu_item_id"),
        update_columns=(),
    )

    all_movement_rows = [
        _timestamped(
            {
                "movement_code": row.values["movement_code"],
                "branch_id": branch_ids[row.values["branch_code"]],
                "ingredient_id": ingredient_ids[
                    row.values["ingredient_code"]
                ],
                "supplier_id": None,
                "movement_type": row.values["movement_type"],
                "quantity": row.values["quantity"],
                "movement_date": row.values["movement_date"],
                "reference": row.values["reference"],
                "reason": row.values["reason"],
                "data_type": row.values["data_type"],
            },
            now=now,
        )
        for row in data.stock_movements
    ]
    movement_rows = await _filter_replayed_movements(
        session,
        all_movement_rows,
        data.stock_movements,
    )
    successful_records += await _upsert(
        session,
        StockMovement,
        movement_rows,
        conflict_columns=("movement_code",),
        update_columns=(),
    )
    await _filter_replayed_movements(
        session,
        all_movement_rows,
        data.stock_movements,
    )

    return successful_records


async def _create_batch(
    session_factory: SessionFactory,
    source_filename: str,
) -> int:
    async with session_factory() as session, session.begin():
        batch = ImportBatch(
            source_filename=source_filename,
            status="running",
        )
        session.add(batch)
        await session.flush()
        if batch.id is None:
            raise RuntimeError("Import batch did not receive a database ID.")
        return batch.id


async def _update_batch(
    session_factory: SessionFactory,
    batch_id: int,
    *,
    status: str,
    total_records: int,
    successful_records: int,
    failed_records: int,
    error_summary: str | None,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .values(
                status=status,
                total_records=total_records,
                successful_records=successful_records,
                failed_records=failed_records,
                error_summary=error_summary,
                completed_at=utc_now() if status != "running" else None,
                updated_at=utc_now(),
            )
        )


def _format_summary(
    *,
    source_rows: int,
    normalized_records: int,
    successful_records: int,
    rejected_records: int,
    issues: Sequence[ImportIssue] = (),
) -> str:
    return json.dumps(
        {
            "source_rows": source_rows,
            "normalized_records": normalized_records,
            "successful_records": successful_records,
            "rejected_records": rejected_records,
            "issues": [str(issue) for issue in issues],
        },
        ensure_ascii=True,
    )


async def import_workbook(
    session_factory: SessionFactory,
    workbook_path: str | Path,
) -> ImportResult:
    """Validate a workbook and import it atomically, recording batch status."""
    path = Path(workbook_path)
    batch_id = await _create_batch(session_factory, path.name)

    try:
        data = read_workbook(path)
    except WorkbookValidationError as exc:
        rejected_records = exc.normalized_records
        summary = _format_summary(
            source_rows=exc.source_rows,
            normalized_records=exc.normalized_records,
            successful_records=0,
            rejected_records=rejected_records,
            issues=exc.issues,
        )
        await _update_batch(
            session_factory,
            batch_id,
            status="failed",
            total_records=exc.normalized_records,
            successful_records=0,
            failed_records=rejected_records,
            error_summary=summary,
        )
        return ImportResult(
            batch_id=batch_id,
            status="failed",
            source_rows=exc.source_rows,
            normalized_records=exc.normalized_records,
            successful_records=0,
            rejected_records=rejected_records,
            issues=exc.issues,
        )

    try:
        async with session_factory() as session, session.begin():
            successful_records = await _upsert_entities(session, data)
            await session.execute(
                update(ImportBatch)
                .where(ImportBatch.id == batch_id)
                .values(
                    status="completed",
                    total_records=data.total_records,
                    successful_records=successful_records,
                    failed_records=0,
                    error_summary=_format_summary(
                        source_rows=data.source_rows,
                        normalized_records=data.total_records,
                        successful_records=successful_records,
                        rejected_records=0,
                    ),
                    completed_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
    except ImportConflictError as exc:
        rejected_records = data.total_records
        summary = _format_summary(
            source_rows=data.source_rows,
            normalized_records=data.total_records,
            successful_records=0,
            rejected_records=rejected_records,
            issues=(exc.issue,),
        )
        await _update_batch(
            session_factory,
            batch_id,
            status="failed",
            total_records=data.total_records,
            successful_records=0,
            failed_records=rejected_records,
            error_summary=summary,
        )
        return ImportResult(
            batch_id=batch_id,
            status="failed",
            source_rows=data.source_rows,
            normalized_records=data.total_records,
            successful_records=0,
            rejected_records=rejected_records,
            issues=(exc.issue,),
        )
    except Exception as exc:
        logger.exception(
            "Import batch %s failed; the entity transaction was rolled back.",
            batch_id,
        )
        issue = ImportIssue(
            "Database",
            None,
            "Entity transaction rolled back after "
            f"{type(exc).__name__}; see application error handling for details.",
        )
        rejected_records = data.total_records
        summary = _format_summary(
            source_rows=data.source_rows,
            normalized_records=data.total_records,
            successful_records=0,
            rejected_records=rejected_records,
            issues=(issue,),
        )
        await _update_batch(
            session_factory,
            batch_id,
            status="failed",
            total_records=data.total_records,
            successful_records=0,
            failed_records=rejected_records,
            error_summary=summary,
        )
        return ImportResult(
            batch_id=batch_id,
            status="failed",
            source_rows=data.source_rows,
            normalized_records=data.total_records,
            successful_records=0,
            rejected_records=rejected_records,
            issues=(issue,),
        )

    return ImportResult(
        batch_id=batch_id,
        status="completed",
        source_rows=data.source_rows,
        normalized_records=data.total_records,
        successful_records=successful_records,
        rejected_records=0,
    )
