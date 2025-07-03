"""Database backup and restore utilities."""

import os
import shutil
from datetime import datetime
from flask import current_app
from app import db


def _get_db_path():
    """Return the filesystem path to the database file."""
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///'):
        return db_uri.replace('sqlite:///', '', 1)
    raise RuntimeError('Only sqlite databases are supported')


def create_backup():
    """Create a timestamped copy of the database."""
    backups_dir = current_app.config['BACKUP_FOLDER']
    os.makedirs(backups_dir, exist_ok=True)
    db_path = _get_db_path()
    filename = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(backups_dir, filename)
    db.session.commit()
    db.engine.dispose()
    shutil.copyfile(db_path, backup_path)
    return filename


def restore_backup(file_path):
    """Restore the database from the specified file."""
    db_path = _get_db_path()
    db.session.remove()
    db.engine.dispose()
    shutil.copyfile(file_path, db_path)
