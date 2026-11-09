from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.worksheet import Worksheet

EXPECTED_SHEETS = {
    "START_HERE",
    "Dashboard",
    "Branches",
    "Ingredients",
    "Branch_Stock",
    "Recipes",
    "Menu_Availability",
    "Stock_Movements",
    "Suppliers",
}

REQUIRED_COLUMNS = {
    "Branches": {
        "Branch_ID",
        "Branch_Name",
        "Address_Demo",
        "Tables",
        "Seats",
        "Hours",
        "Status",
    },
    "Ingredients": {
        "Ingredient_ID",
        "Ingredient_Name",
        "Category",
        "Unit",
        "Unit_Cost_PKR",
        "Default_Reorder",
        "Default_Target",
        "Supplier_ID",
        "Status",
    },
    "Branch_Stock": {
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
        "Reorder_Level",
        "Target_Stock",
        "Unit_Cost_PKR",
    },
    "Recipes": {
        "Menu_ID",
        "Menu_Item",
        "Category",
        "Ingredient_ID",
        "Qty_Per_Portion",
    },
    "Menu_Availability": {
        "Menu_ID",
        "Menu_Item",
        "Category",
        "Menu_Status",
    },
    "Stock_Movements": {
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
    },
    "Suppliers": {
        "Supplier_ID",
        "Supplier_Name",
        "Supply_Category",
        "Contact",
        "Verification",
    },
}

MAX_RECORDS = 100_000


@dataclass(frozen=True)
class ImportIssue:
    worksheet: str
    row_number: int | None
    message: str

    def __str__(self) -> str:
        location = self.worksheet
        if self.row_number is not None:
            location += f" row {self.row_number}"
        return f"{location}: {self.message}"


class WorkbookValidationError(ValueError):
    def __init__(
        self,
        issues: list[ImportIssue],
        *,
        source_rows: int = 0,
        normalized_records: int = 0,
    ) -> None:
        self.issues = tuple(issues)
        self.source_rows = source_rows
        self.normalized_records = normalized_records
        super().__init__("\n".join(str(issue) for issue in issues))


@dataclass(frozen=True)
class SourceRow:
    row_number: int
    values: dict[str, Any]


@dataclass(frozen=True)
class WorkbookData:
    branches: tuple[SourceRow, ...]
    suppliers: tuple[SourceRow, ...]
    ingredients: tuple[SourceRow, ...]
    branch_stocks: tuple[SourceRow, ...]
    menu_items: tuple[SourceRow, ...]
    recipe_items: tuple[SourceRow, ...]
    menu_availability: tuple[SourceRow, ...]
    stock_movements: tuple[SourceRow, ...]
    source_rows: int

    @property
    def total_records(self) -> int:
        """Return the number of normalized entity records, not source rows."""
        return sum(
            len(records)
            for records in (
                self.branches,
                self.suppliers,
                self.ingredients,
                self.branch_stocks,
                self.menu_items,
                self.recipe_items,
                self.menu_availability,
                self.stock_movements,
            )
        )


def _read_rows(
    worksheet: Worksheet,
    required_columns: set[str],
    issues: list[ImportIssue],
) -> list[tuple[int, dict[str, Any]]]:
    header_values = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True))
    headers: list[str] = []
    for column_number, value in enumerate(header_values, start=1):
        header = str(value).strip() if value is not None else ""
        headers.append(header)
        if not header:
            issues.append(
                ImportIssue(
                    worksheet.title,
                    1,
                    f"Column {column_number} has no header.",
                )
            )

    duplicates = sorted(name for name, count in Counter(headers).items() if name and count > 1)
    if duplicates:
        issues.append(
            ImportIssue(
                worksheet.title,
                1,
                f"Duplicate column headers: {', '.join(duplicates)}.",
            )
        )

    missing = sorted(required_columns - set(headers))
    if missing:
        issues.append(
            ImportIssue(
                worksheet.title,
                1,
                f"Missing required columns: {', '.join(missing)}.",
            )
        )

    records: list[tuple[int, dict[str, Any]]] = []
    for row_number, cells in enumerate(
        worksheet.iter_rows(min_row=2),
        start=2,
    ):
        if not any(cell.value is not None for cell in cells):
            continue
        record = {
            header: cells[index].value
            for index, header in enumerate(headers)
            if header
        }
        records.append((row_number, record))
        if len(records) > MAX_RECORDS:
            issues.append(
                ImportIssue(
                    worksheet.title,
                    row_number,
                    f"Worksheet exceeds the {MAX_RECORDS} row safety limit.",
                )
            )
            break
    return records


def _text(
    row: dict[str, Any],
    field: str,
    *,
    optional: bool = False,
    max_length: int | None = None,
) -> str | None:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError(f"{field} is required.")
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text.")
    cleaned = value.strip()
    if max_length is not None and len(cleaned) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters.")
    return cleaned


def _decimal(
    row: dict[str, Any],
    field: str,
    *,
    scale: int = 3,
    optional: bool = False,
    minimum: Decimal | None = None,
) -> Decimal | None:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError(f"{field} is required.")
    if isinstance(value, bool):
        raise TypeError(f"{field} must be numeric.")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be numeric.") from None
    if not number.is_finite():
        raise ValueError(f"{field} must be finite.")
    quantum = Decimal(1).scaleb(-scale)
    try:
        rounded = number.quantize(quantum)
    except InvalidOperation:
        raise ValueError(f"{field} exceeds supported precision.") from None
    if rounded != number:
        raise ValueError(f"{field} supports at most {scale} decimal places.")
    if abs(number) >= Decimal(10) ** (14 - scale):
        raise ValueError(f"{field} exceeds supported precision.")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} must be at least {minimum}.")
    return number


def _integer(
    row: dict[str, Any],
    field: str,
    *,
    minimum: int = 0,
) -> int:
    value = _decimal(row, field, scale=0, minimum=Decimal(minimum))
    assert value is not None
    return int(value)


def _status(row: dict[str, Any], field: str) -> bool:
    value = _text(row, field)
    assert value is not None
    normalized = value.casefold()
    if normalized == "active":
        return True
    if normalized == "inactive":
        return False
    raise ValueError(f"{field} must be Active or Inactive; got {value!r}.")


def _date(row: dict[str, Any], field: str) -> date:
    value = row.get(field)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).") from None


def _parse_rows(
    worksheet: str,
    records: list[tuple[int, dict[str, Any]]],
    parser: Any,
    issues: list[ImportIssue],
) -> list[SourceRow]:
    parsed: list[SourceRow] = []
    for row_number, raw in records:
        try:
            values = parser(raw)
        except (TypeError, ValueError) as exc:
            issues.append(ImportIssue(worksheet, row_number, str(exc)))
            continue
        parsed.append(SourceRow(row_number, values))
    return parsed


def _check_unique(
    worksheet: str,
    rows: tuple[SourceRow, ...] | list[SourceRow],
    key_fields: tuple[str, ...],
    issues: list[ImportIssue],
) -> None:
    seen: dict[tuple[Any, ...], int] = {}
    for source_row in rows:
        key = tuple(source_row.values[field] for field in key_fields)
        prior_row = seen.get(key)
        if prior_row is not None:
            issues.append(
                ImportIssue(
                    worksheet,
                    source_row.row_number,
                    f"Duplicate key {key!r}; first seen on row {prior_row}.",
                )
            )
        else:
            seen[key] = source_row.row_number


def _check_foreign_key(
    worksheet: str,
    row: SourceRow,
    field: str,
    known_ids: set[str],
    issues: list[ImportIssue],
) -> None:
    value = row.values[field]
    if value not in known_ids:
        issues.append(
            ImportIssue(
                worksheet,
                row.row_number,
                f"{field} references unknown source ID {value!r}.",
            )
        )


def read_workbook(path: str | Path) -> WorkbookData:
    """Read and validate rows; availability is unknown unless separately resolved.

    Menu availability source rows do not contain reliable per-branch availability
    values, so normalization creates branch/menu records with ``is_available``
    unset. Formula caches are never used as inventory or availability authority.
    """
    workbook_path = Path(path)
    issues: list[ImportIssue] = []
    try:
        workbook = load_workbook(
            workbook_path,
            data_only=False,
            read_only=True,
        )
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        issue = ImportIssue(
            "Workbook",
            None,
            f"Unable to open {workbook_path.name!r} ({type(exc).__name__}).",
        )
        raise WorkbookValidationError([issue]) from None

    try:
        missing_sheets = sorted(EXPECTED_SHEETS - set(workbook.sheetnames))
        if missing_sheets:
            issues.append(
                ImportIssue(
                    "Workbook",
                    None,
                    f"Missing required worksheets: {', '.join(missing_sheets)}.",
                )
            )

        raw: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for sheet_name, required in REQUIRED_COLUMNS.items():
            if sheet_name not in workbook.sheetnames:
                raw[sheet_name] = []
                continue
            raw[sheet_name] = _read_rows(
                workbook[sheet_name],
                required,
                issues,
            )

        source_rows = sum(len(rows) for rows in raw.values())

        branches = _parse_rows(
            "Branches",
            raw["Branches"],
            lambda row: {
                "branch_code": _text(row, "Branch_ID", max_length=64),
                "name": _text(row, "Branch_Name", max_length=120),
                "address": _text(row, "Address_Demo", optional=True, max_length=300),
                "table_count": _integer(row, "Tables"),
                "seat_capacity": _integer(row, "Seats"),
                "operating_hours": _text(row, "Hours", max_length=100),
                "is_active": _status(row, "Status"),
            },
            issues,
        )
        suppliers = _parse_rows(
            "Suppliers",
            raw["Suppliers"],
            lambda row: {
                "supplier_code": _text(row, "Supplier_ID", max_length=64),
                "name": _text(row, "Supplier_Name", max_length=160),
                "supply_category": _text(
                    row,
                    "Supply_Category",
                    optional=True,
                    max_length=120,
                ),
                "contact": _text(row, "Contact", optional=True, max_length=300),
                "verification_status": _text(
                    row,
                    "Verification",
                    optional=True,
                    max_length=80,
                ),
            },
            issues,
        )
        ingredients = _parse_rows(
            "Ingredients",
            raw["Ingredients"],
            lambda row: {
                "ingredient_code": _text(row, "Ingredient_ID", max_length=64),
                "name": _text(row, "Ingredient_Name", max_length=160),
                "category": _text(row, "Category", optional=True, max_length=120),
                "unit": _text(row, "Unit", max_length=32),
                "unit_cost_pkr": _decimal(
                    row,
                    "Unit_Cost_PKR",
                    scale=2,
                    minimum=Decimal(0),
                ),
                "default_reorder_quantity": _decimal(
                    row,
                    "Default_Reorder",
                    optional=True,
                    minimum=Decimal(0),
                ),
                "default_target_quantity": _decimal(
                    row,
                    "Default_Target",
                    optional=True,
                    minimum=Decimal(0),
                ),
                "supplier_code": _text(row, "Supplier_ID", max_length=64),
                "is_active": _status(row, "Status"),
            },
            issues,
        )

        branch_ids = {row.values["branch_code"] for row in branches}
        supplier_ids = {row.values["supplier_code"] for row in suppliers}
        ingredient_ids = {row.values["ingredient_code"] for row in ingredients}

        branch_stocks = _parse_rows(
            "Branch_Stock",
            raw["Branch_Stock"],
            lambda row: {
                "branch_code": _text(row, "Branch_ID", max_length=64),
                "ingredient_code": _text(row, "Ingredient_ID", max_length=64),
                "source_name": _text(row, "Ingredient_Name", max_length=160),
                "source_category": _text(
                    row,
                    "Category",
                    optional=True,
                    max_length=120,
                ),
                "source_unit": _text(row, "Unit", max_length=32),
                "opening": _decimal(row, "Opening", minimum=Decimal(0)),
                "received": _decimal(row, "Received", minimum=Decimal(0)),
                "consumed": _decimal(row, "Consumed", minimum=Decimal(0)),
                "wastage": _decimal(row, "Wastage", minimum=Decimal(0)),
                "adjustment": _decimal(row, "Adjustment"),
                "reserved_quantity": _decimal(
                    row,
                    "Reserved",
                    minimum=Decimal(0),
                ),
                "reorder_level": _decimal(
                    row,
                    "Reorder_Level",
                    optional=True,
                    minimum=Decimal(0),
                ),
                "target_stock": _decimal(
                    row,
                    "Target_Stock",
                    optional=True,
                    minimum=Decimal(0),
                ),
                "source_unit_cost_pkr": _decimal(
                    row,
                    "Unit_Cost_PKR",
                    scale=2,
                    minimum=Decimal(0),
                ),
            },
            issues,
        )
        for row in branch_stocks:
            _check_foreign_key(
                "Branch_Stock", row, "branch_code", branch_ids, issues
            )
            _check_foreign_key(
                "Branch_Stock", row, "ingredient_code", ingredient_ids, issues
            )
            ingredient = next(
                (
                    item.values
                    for item in ingredients
                    if item.values["ingredient_code"]
                    == row.values["ingredient_code"]
                ),
                None,
            )
            if ingredient is not None:
                for source_field, ingredient_field in (
                    ("source_name", "name"),
                    ("source_category", "category"),
                    ("source_unit", "unit"),
                    ("source_unit_cost_pkr", "unit_cost_pkr"),
                ):
                    if row.values[source_field] != ingredient[ingredient_field]:
                        issues.append(
                            ImportIssue(
                                "Branch_Stock",
                                row.row_number,
                                f"{source_field} conflicts with the Ingredients "
                                f"master row for {row.values['ingredient_code']!r}.",
                            )
                        )
            calculated_quantity = (
                row.values["opening"]
                + row.values["received"]
                - row.values["consumed"]
                - row.values["wastage"]
                + row.values["adjustment"]
            )
            if calculated_quantity < 0:
                issues.append(
                    ImportIssue(
                        "Branch_Stock",
                        row.row_number,
                        "Calculated quantity_on_hand cannot be negative.",
                    )
                )
            elif calculated_quantity >= Decimal(10) ** 11:
                issues.append(
                    ImportIssue(
                        "Branch_Stock",
                        row.row_number,
                        "Calculated quantity_on_hand exceeds Numeric(14, 3).",
                    )
                )

        recipes = _parse_rows(
            "Recipes",
            raw["Recipes"],
            lambda row: {
                "menu_code": _text(row, "Menu_ID", max_length=64),
                "menu_name": _text(row, "Menu_Item", max_length=180),
                "category": _text(row, "Category", optional=True, max_length=120),
                "ingredient_code": _text(row, "Ingredient_ID", max_length=64),
                "quantity_per_portion": _decimal(
                    row,
                    "Qty_Per_Portion",
                    minimum=Decimal("0.001"),
                ),
            },
            issues,
        )
        _check_unique(
            "Recipes",
            recipes,
            ("menu_code", "ingredient_code"),
            issues,
        )
        for row in recipes:
            _check_foreign_key(
                "Recipes", row, "ingredient_code", ingredient_ids, issues
            )

        availability = _parse_rows(
            "Menu_Availability",
            raw["Menu_Availability"],
            lambda row: {
                "menu_code": _text(row, "Menu_ID", max_length=64),
                "menu_name": _text(row, "Menu_Item", max_length=180),
                "category": _text(row, "Category", optional=True, max_length=120),
                "is_active": _status(row, "Menu_Status"),
            },
            issues,
        )
        _check_unique("Menu_Availability", availability, ("menu_code",), issues)

        recipe_menu: dict[str, tuple[str, str | None, int]] = {}
        for row in recipes:
            values = row.values
            identity = (values["menu_name"], values["category"])
            prior = recipe_menu.get(values["menu_code"])
            if prior is not None and prior[:2] != identity:
                issues.append(
                    ImportIssue(
                        "Recipes",
                        row.row_number,
                        f"Menu ID {values['menu_code']!r} has conflicting "
                        "name or category values.",
                    )
                )
            else:
                recipe_menu[values["menu_code"]] = (
                    values["menu_name"],
                    values["category"],
                    row.row_number,
                )

        for row in availability:
            code = row.values["menu_code"]
            recipe_identity = recipe_menu.get(code)
            if recipe_identity is None:
                issues.append(
                    ImportIssue(
                        "Menu_Availability",
                        row.row_number,
                        f"Menu_ID {code!r} has no recipe rows.",
                    )
                )
            elif recipe_identity[:2] != (
                row.values["menu_name"],
                row.values["category"],
            ):
                issues.append(
                    ImportIssue(
                        "Menu_Availability",
                        row.row_number,
                        f"Menu_ID {code!r} conflicts with its Recipes name or category.",
                    )
                )
        availability_ids = {row.values["menu_code"] for row in availability}
        for row in recipes:
            if row.values["menu_code"] not in availability_ids:
                issues.append(
                    ImportIssue(
                        "Recipes",
                        row.row_number,
                        f"Menu_ID {row.values['menu_code']!r} is missing from "
                        "Menu_Availability.",
                    )
                )

        movements = _parse_rows(
            "Stock_Movements",
            raw["Stock_Movements"],
            lambda row: {
                "movement_code": _text(row, "Movement_ID", max_length=64),
                "movement_date": _date(row, "Movement_Date"),
                "branch_code": _text(row, "Branch_ID", max_length=64),
                "ingredient_code": _text(row, "Ingredient_ID", max_length=64),
                "source_unit": _text(row, "Unit", max_length=32),
                "movement_type": _text(row, "Movement_Type", max_length=40),
                "quantity": _decimal(row, "Qty_Signed"),
                "reference": _text(row, "Reference", optional=True, max_length=160),
                "reason": _text(row, "Reason", optional=True),
                "data_type": _text(row, "Data_Type", optional=True, max_length=40),
            },
            issues,
        )
        for row in movements:
            _check_foreign_key(
                "Stock_Movements", row, "branch_code", branch_ids, issues
            )
            _check_foreign_key(
                "Stock_Movements", row, "ingredient_code", ingredient_ids, issues
            )
            ingredient = next(
                (
                    item.values
                    for item in ingredients
                    if item.values["ingredient_code"]
                    == row.values["ingredient_code"]
                ),
                None,
            )
            if (
                ingredient is not None
                and row.values["source_unit"] != ingredient["unit"]
            ):
                issues.append(
                    ImportIssue(
                        "Stock_Movements",
                        row.row_number,
                        f"Unit conflicts with the Ingredients master row for "
                        f"{row.values['ingredient_code']!r}.",
                    )
                )

        _check_unique("Branches", branches, ("branch_code",), issues)
        _check_unique("Suppliers", suppliers, ("supplier_code",), issues)
        _check_unique(
            "Ingredients",
            ingredients,
            ("ingredient_code",),
            issues,
        )
        _check_unique(
            "Branch_Stock",
            branch_stocks,
            ("branch_code", "ingredient_code"),
            issues,
        )
        _check_unique(
            "Stock_Movements",
            movements,
            ("movement_code",),
            issues,
        )

        for row in ingredients:
            _check_foreign_key(
                "Ingredients", row, "supplier_code", supplier_ids, issues
            )

        normalized_menu_codes = {
            row.values["menu_code"] for row in availability
        }
        normalized_records = (
            len(branches)
            + len(suppliers)
            + len(ingredients)
            + len(branch_stocks)
            + len(normalized_menu_codes)
            + len(recipes)
            + len(normalized_menu_codes) * len(branches)
            + len(movements)
        )
        if issues:
            raise WorkbookValidationError(
                issues,
                source_rows=source_rows,
                normalized_records=normalized_records,
            )

        menu_items_by_code = {
            row.values["menu_code"]: row for row in availability
        }
        branches_by_code = {row.values["branch_code"]: row for row in branches}
        normalized_stock = tuple(
            SourceRow(
                row.row_number,
                {
                    "branch_code": row.values["branch_code"],
                    "ingredient_code": row.values["ingredient_code"],
                    "quantity_on_hand": (
                        row.values["opening"]
                        + row.values["received"]
                        - row.values["consumed"]
                        - row.values["wastage"]
                        + row.values["adjustment"]
                    ),
                    "reserved_quantity": row.values["reserved_quantity"],
                    "reorder_level": row.values["reorder_level"],
                    "target_stock": row.values["target_stock"],
                },
            )
            for row in branch_stocks
        )
        normalized_menus = tuple(
            SourceRow(
                source_row.row_number,
                {
                    "menu_code": code,
                    "name": source_row.values["menu_name"],
                    "category": source_row.values["category"],
                    "is_active": source_row.values["is_active"],
                },
            )
            for code, source_row in menu_items_by_code.items()
        )
        normalized_recipes = tuple(
            SourceRow(
                row.row_number,
                {
                    "menu_code": row.values["menu_code"],
                    "ingredient_code": row.values["ingredient_code"],
                    "quantity_per_portion": row.values["quantity_per_portion"],
                },
            )
            for row in recipes
        )
        normalized_availability = tuple(
            SourceRow(
                menu_row.row_number,
                {"branch_code": branch_code, "menu_code": menu_code},
            )
            for menu_code, menu_row in menu_items_by_code.items()
            for branch_code in branches_by_code
        )

        return WorkbookData(
            branches=tuple(branches),
            suppliers=tuple(suppliers),
            ingredients=tuple(ingredients),
            branch_stocks=normalized_stock,
            menu_items=normalized_menus,
            recipe_items=normalized_recipes,
            menu_availability=normalized_availability,
            stock_movements=tuple(movements),
            source_rows=source_rows,
        )
    finally:
        workbook.close()
