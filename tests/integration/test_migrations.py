import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

EXPECTED_TABLES = {
    "alembic_version",
    "discovered_chats",
    "leads",
    "monitored_chats",
    "portfolio_items",
    "search_queries",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_alembic_config(database_path: Path) -> Config:
    config = Config(str(project_root() / "alembic.ini"))
    config.set_main_option("script_location", str(project_root() / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    return config


def read_table_names(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("select name from sqlite_master where type='table'").fetchall()
    return {row[0] for row in rows}


def test_migrations_build_schema_from_scratch(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    config = build_alembic_config(database_path)

    command.upgrade(config, "head")

    assert read_table_names(database_path) >= EXPECTED_TABLES


def test_migrations_downgrade_to_base(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    config = build_alembic_config(database_path)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    assert read_table_names(database_path) <= {"alembic_version"}
