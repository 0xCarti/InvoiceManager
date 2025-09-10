"""Database backup and restore utilities."""

import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from threading import Event, Thread

from flask import current_app

from app import db

UNIT_SECONDS = {
    "hour": 60 * 60,
    "day": 60 * 60 * 24,
    "week": 60 * 60 * 24 * 7,
    "month": 60 * 60 * 24 * 30,
    "year": 60 * 60 * 24 * 365,
}

_backup_thread: Thread | None = None
_stop_event = Event()


def _get_db_path():
    """Return the filesystem path to the database file."""
    db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        return db_uri.replace("sqlite:///", "", 1)
    raise RuntimeError("Only sqlite databases are supported")


def create_backup():
    """Create a timestamped copy of the database."""
    backups_dir = current_app.config["BACKUP_FOLDER"]
    os.makedirs(backups_dir, exist_ok=True)
    try:
        os.chmod(backups_dir, 0o777)
    except OSError:
        pass
    max_backups = current_app.config.get("MAX_BACKUPS")
    files = sorted(f for f in os.listdir(backups_dir) if f.endswith(".db"))
    if max_backups:
        while len(files) >= int(max_backups):
            oldest = files.pop(0)
            try:
                os.remove(os.path.join(backups_dir, oldest))
            except OSError:
                pass
    db_path = _get_db_path()
    filename = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(backups_dir, filename)
    db.session.commit()
    db.engine.dispose()
    shutil.copyfile(db_path, backup_path)

    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info("Created backup %s", filename)

    return filename


def _backup_loop(app, interval: int):
    while not _stop_event.wait(interval):
        with app.app_context():
            create_backup()


def start_auto_backup_thread(app):
    """Start or restart the automatic backup thread based on app config."""
    global _backup_thread, _stop_event
    if _backup_thread and _backup_thread.is_alive():
        _stop_event.set()
        _backup_thread.join()
        _stop_event = Event()

    if not app.config.get("AUTO_BACKUP_ENABLED"):
        return

    interval = app.config.get("AUTO_BACKUP_INTERVAL")
    if not interval:
        return
    _backup_thread = Thread(
        target=_backup_loop, args=(app, interval), daemon=True
    )
    _backup_thread.start()


__all__ = [
    "create_backup",
    "restore_backup",
    "start_auto_backup_thread",
    "UNIT_SECONDS",
]


def restore_backup(file_path):
    """Restore the database from the specified file.

    The backup is read using a separate SQLite connection. The current database
    is rebuilt using the models defined in the application. For each table we
    copy rows from the backup, inserting only the columns that exist in the
    current schema and supplying defaults for any new columns.
    """

    # Open the backup file in a separate SQLite connection
    backup_conn = sqlite3.connect(
        file_path, detect_types=sqlite3.PARSE_DECLTYPES
    )
    backup_conn.row_factory = sqlite3.Row
    backup_cursor = backup_conn.cursor()

    # Reset current session and rebuild schema based on models
    db.session.remove()
    db.drop_all()
    db.create_all()

    logger = current_app.logger if current_app else logging.getLogger(__name__)

    # Iterate over all tables in dependency order
    for table in db.metadata.sorted_tables:
        table_name = table.name

        # Ensure the table exists in the backup database
        backup_cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        if not backup_cursor.fetchone():
            logger.info("Table %s missing from backup", table_name)
            continue

        # Columns present in backup
        backup_cursor.execute(f"PRAGMA table_info({table_name})")
        backup_cols = {row[1] for row in backup_cursor.fetchall()}

        current_cols = {c.name for c in table.columns}
        missing_cols = current_cols - backup_cols
        extra_cols = backup_cols - current_cols
        if missing_cols or extra_cols:
            logger.info(
                "Schema mismatch for %s; missing=%s, extra=%s",
                table_name,
                sorted(missing_cols),
                sorted(extra_cols),
            )

        # Only select columns that exist in both schemas
        select_cols = [c for c in table.columns if c.name in backup_cols]
        col_names = ", ".join(c.name for c in select_cols)
        backup_cursor.execute(f"SELECT {col_names} FROM {table_name}")
        rows = backup_cursor.fetchall()

        insert_rows = []
        for row in rows:
            record = {col.name: row[col.name] for col in select_cols}

            for col in table.columns:
                if col.name not in record:
                    default = None
                    if col.default is not None:
                        default = col.default.arg
                        if callable(default):
                            try:
                                default = default()
                            except TypeError:
                                default = default(None)
                    record[col.name] = default
                else:
                    value = record[col.name]
                    if isinstance(col.type, db.DateTime) and isinstance(
                        value, str
                    ):
                        try:
                            record[col.name] = datetime.fromisoformat(value)
                        except ValueError:
                            pass
                    elif isinstance(col.type, db.Date) and isinstance(
                        value, str
                    ):
                        try:
                            record[col.name] = datetime.fromisoformat(
                                value
                            ).date()
                        except ValueError:
                            pass

            insert_rows.append(record)

        if insert_rows:
            db.session.execute(table.insert(), insert_rows)

    db.session.commit()
    backup_conn.close()
