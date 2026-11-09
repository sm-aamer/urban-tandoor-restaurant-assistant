from datetime import UTC
from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint, inspect
from sqlalchemy.orm import configure_mappers
from sqlalchemy.types import JSON
from sqlmodel import SQLModel

from app.models import (
    Branch,
    BranchStock,
    ImportBatch,
    Ingredient,
    MenuAvailability,
    MenuItem,
    RecipeItem,
    RestaurantDocument,
    StockMovement,
    Supplier,
)

EXPECTED_TABLES = {
    "branch",
    "branch_stock",
    "import_batch",
    "ingredient",
    "menu_availability",
    "menu_item",
    "recipe_item",
    "restaurant_document",
    "stock_movement",
    "supplier",
}


def test_all_models_are_imported_and_registered() -> None:
    assert {
        Branch,
        BranchStock,
        ImportBatch,
        Ingredient,
        MenuAvailability,
        MenuItem,
        RecipeItem,
        RestaurantDocument,
        StockMovement,
        Supplier,
    }
    assert set(SQLModel.metadata.tables) == EXPECTED_TABLES


def test_each_table_has_an_integer_primary_key() -> None:
    for table in SQLModel.metadata.tables.values():
        primary_key_columns = list(table.primary_key.columns)
        assert [column.name for column in primary_key_columns] == ["id"]
        assert isinstance(primary_key_columns[0].type.python_type, type)
        assert primary_key_columns[0].type.python_type is int


def test_foreign_keys_reference_expected_tables() -> None:
    expected_foreign_keys = {
        "ingredient": {"supplier_id": "supplier.id"},
        "branch_stock": {
            "branch_id": "branch.id",
            "ingredient_id": "ingredient.id",
        },
        "recipe_item": {
            "menu_item_id": "menu_item.id",
            "ingredient_id": "ingredient.id",
        },
        "menu_availability": {
            "branch_id": "branch.id",
            "menu_item_id": "menu_item.id",
        },
        "stock_movement": {
            "branch_id": "branch.id",
            "ingredient_id": "ingredient.id",
            "supplier_id": "supplier.id",
        },
        "restaurant_document": {"branch_id": "branch.id"},
    }

    for table_name, expected in expected_foreign_keys.items():
        table = SQLModel.metadata.tables[table_name]
        actual = {
            column.name: next(iter(column.foreign_keys)).target_fullname
            for column in table.columns
            if column.foreign_keys
        }
        assert actual == expected


def test_relationships_are_configured_with_back_populates() -> None:
    configure_mappers()
    expected_relationships = {
        Branch: {
            "stock_records": BranchStock,
            "menu_availability": MenuAvailability,
            "stock_movements": StockMovement,
            "documents": RestaurantDocument,
        },
        Supplier: {
            "ingredients": Ingredient,
            "stock_movements": StockMovement,
        },
        Ingredient: {
            "supplier": Supplier,
            "branch_stocks": BranchStock,
            "recipe_items": RecipeItem,
            "stock_movements": StockMovement,
        },
        BranchStock: {"branch": Branch, "ingredient": Ingredient},
        MenuItem: {
            "recipe_items": RecipeItem,
            "availability_records": MenuAvailability,
        },
        RecipeItem: {"menu_item": MenuItem, "ingredient": Ingredient},
        MenuAvailability: {"branch": Branch, "menu_item": MenuItem},
        StockMovement: {
            "branch": Branch,
            "ingredient": Ingredient,
            "supplier": Supplier,
        },
        RestaurantDocument: {"branch": Branch},
    }

    for model, relationships in expected_relationships.items():
        actual = inspect(model).relationships
        assert set(actual.keys()) == set(relationships)
        for relationship_name, target_model in relationships.items():
            assert actual[relationship_name].mapper.class_ is target_model
            assert actual[relationship_name].back_populates is not None


def test_source_identifiers_and_composite_pairs_are_unique() -> None:
    for table_name, column_name in (
        ("branch", "branch_code"),
        ("supplier", "supplier_code"),
        ("ingredient", "ingredient_code"),
        ("menu_item", "menu_code"),
        ("stock_movement", "movement_code"),
    ):
        column = SQLModel.metadata.tables[table_name].c[column_name]
        assert column.unique

    expected_constraints = {
        "branch_stock": {"branch_id", "ingredient_id"},
        "recipe_item": {"menu_item_id", "ingredient_id"},
        "menu_availability": {"branch_id", "menu_item_id"},
    }
    for table_name, expected_columns in expected_constraints.items():
        constraints = SQLModel.metadata.tables[table_name].constraints
        assert any(
            isinstance(constraint, UniqueConstraint)
            and {column.name for column in constraint.columns} == expected_columns
            for constraint in constraints
        )


def test_query_indexes_are_defined() -> None:
    for table_name, expected_indexes in {
        "ingredient": {"ix_ingredient_supplier_id"},
        "branch_stock": {"ix_branch_stock_ingredient_id"},
        "recipe_item": {"ix_recipe_item_ingredient_id"},
        "menu_availability": {"ix_menu_availability_menu_item_id"},
        "stock_movement": {
            "ix_stock_movement_supplier_id",
            "ix_stock_movement_branch_date",
            "ix_stock_movement_ingredient_date",
        },
        "import_batch": {"ix_import_batch_status"},
        "restaurant_document": {
            "ix_restaurant_document_document_type",
            "ix_restaurant_document_source_identifier",
            "ix_restaurant_document_branch_id",
            "ix_restaurant_document_content_hash",
        },
    }.items():
        actual_indexes = {
            index.name for index in SQLModel.metadata.tables[table_name].indexes
        }
        assert expected_indexes <= actual_indexes


def test_quantities_and_prices_use_exact_numeric_columns() -> None:
    numeric_columns = (
        ("ingredient", "unit_cost_pkr"),
        ("ingredient", "default_reorder_quantity"),
        ("ingredient", "default_target_quantity"),
        ("branch_stock", "quantity_on_hand"),
        ("branch_stock", "reserved_quantity"),
        ("branch_stock", "reorder_level"),
        ("branch_stock", "target_stock"),
        ("menu_item", "price_pkr"),
        ("recipe_item", "quantity_per_portion"),
        ("stock_movement", "quantity"),
    )
    for table_name, column_name in numeric_columns:
        assert isinstance(
            SQLModel.metadata.tables[table_name].c[column_name].type,
            Numeric,
        )

    assert isinstance(Decimal("0.005"), Decimal)


def test_application_timestamps_are_utc_aware() -> None:
    branch = Branch(branch_code="TEST", name="Test Branch")

    assert branch.created_at.utcoffset().total_seconds() == 0
    assert branch.updated_at.utcoffset().total_seconds() == 0
    assert branch.created_at.tzinfo is UTC
    assert branch.updated_at.tzinfo is UTC
    for table_name in EXPECTED_TABLES:
        table = SQLModel.metadata.tables[table_name]
        assert table.c.created_at.type.timezone
        assert table.c.updated_at.type.timezone


def test_source_transaction_date_is_date_and_document_metadata_is_json() -> None:
    movement_date = SQLModel.metadata.tables["stock_movement"].c.movement_date
    document_metadata = SQLModel.metadata.tables["restaurant_document"].c.metadata_json

    assert movement_date.type.python_type.__name__ == "date"
    assert isinstance(document_metadata.type, JSON)
