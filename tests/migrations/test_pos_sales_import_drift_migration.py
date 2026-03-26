from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
ENV_TEMPLATE = """
from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

target_metadata = None


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
""".strip()


@pytest.fixture(autouse=True)
def gl_codes():
    """Override root autouse fixture so this module stays migration-only."""
    pass


def _make_alembic_script_dir(tmp_path: Path) -> Path:
    script_dir = tmp_path / "alembic_runtime"
    versions_link = script_dir / "versions"
    script_dir.mkdir()
    (script_dir / "env.py").write_text(ENV_TEMPLATE)
    versions_link.symlink_to(VERSIONS_DIR, target_is_directory=True)
    return script_dir


def _alembic_config(db_path: Path, script_dir: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(script_dir))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def _create_fk_target_tables(db_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE IF NOT EXISTS user (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE IF NOT EXISTS location (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE IF NOT EXISTS product (id INTEGER PRIMARY KEY)"))


def test_upgrade_handles_preexisting_approval_metadata_column(tmp_path):
    db_path = tmp_path / "drifted_schema.db"
    script_dir = _make_alembic_script_dir(tmp_path)
    config = _alembic_config(db_path, script_dir)

    # Avoid replaying unrelated historical revisions; start right before 202603260001.
    command.stamp(config, "202603210002")
    _create_fk_target_tables(db_path)
    command.upgrade(config, "202603260002")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(sa.text("ALTER TABLE pos_sales_import_row ADD COLUMN approval_metadata TEXT"))

    command.upgrade(config, "head")

    expected_head = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current_revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current_revision == expected_head

        columns = connection.execute(sa.text("PRAGMA table_info('pos_sales_import_row')")).mappings().all()

    approval_metadata_columns = [column for column in columns if column["name"] == "approval_metadata"]
    assert len(approval_metadata_columns) == 1
