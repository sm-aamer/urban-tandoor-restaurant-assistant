import re
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlmodel import SQLModel

from alembic import command
from app import models

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def make_alembic_config(output_buffer: StringIO | None = None) -> Config:
    return Config(
        str(PROJECT_ROOT / "alembic.ini"),
        output_buffer=output_buffer,
    )


def render_revision_operation(operation_name: str) -> str:
    script_directory = ScriptDirectory.from_config(make_alembic_config())
    revision = script_directory.get_revision("head")
    assert revision is not None

    output_buffer = StringIO()
    migration_context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output_buffer},
    )
    with Operations.context(migration_context):
        getattr(revision.module, operation_name)()

    return output_buffer.getvalue()


def test_alembic_configuration_uses_project_migration_directory() -> None:
    config = make_alembic_config()
    script_directory = ScriptDirectory.from_config(config)

    assert Path(script_directory.dir).resolve() == (PROJECT_ROOT / "alembic").resolve()
    assert config.get_section("alembic") is not None
    assert config.get_section("alembic").get("sqlalchemy.url") is None


def test_all_model_tables_are_available_to_alembic() -> None:
    assert len(models.__all__) == len(EXPECTED_TABLES)
    assert set(SQLModel.metadata.tables) == EXPECTED_TABLES


def test_initial_revision_contains_all_tables_and_no_destructive_upgrade_ops() -> None:
    upgrade_sql = render_revision_operation("upgrade")
    created_tables = re.findall(r"CREATE TABLE (\w+) \(", upgrade_sql)

    assert set(created_tables) == EXPECTED_TABLES
    assert len(created_tables) == len(EXPECTED_TABLES)
    assert "DROP TABLE" not in upgrade_sql
    assert "NUMERIC(14, 2)" in upgrade_sql
    assert "NUMERIC(14, 3)" in upgrade_sql
    assert "TIMESTAMP WITH TIME ZONE" in upgrade_sql
    assert "metadata_json JSON NOT NULL" in upgrade_sql
    assert "FOREIGN KEY(branch_id) REFERENCES branch (id) ON DELETE SET NULL" in (
        upgrade_sql
    )
    assert "uq_branch_stock_branch_ingredient" in upgrade_sql
    assert "uq_recipe_item_menu_ingredient" in upgrade_sql
    assert "uq_menu_availability_branch_menu_item" in upgrade_sql


def test_initial_revision_downgrade_drops_tables_in_reverse_order() -> None:
    upgrade_sql = render_revision_operation("upgrade")
    downgrade_sql = render_revision_operation("downgrade")
    created_tables = re.findall(r"CREATE TABLE (\w+) \(", upgrade_sql)
    dropped_tables = re.findall(r"DROP TABLE (\w+)", downgrade_sql)

    assert dropped_tables == list(reversed(created_tables))


def test_alembic_environment_generates_offline_sql_without_a_connection() -> None:
    output_buffer = StringIO()
    command.upgrade(make_alembic_config(output_buffer), "head", sql=True)
    generated_sql = output_buffer.getvalue()

    assert all(f"CREATE TABLE {table} (" in generated_sql for table in EXPECTED_TABLES)
