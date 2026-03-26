#!/bin/sh
set -e

if ! flask db upgrade; then
    echo >&2 "[entrypoint] Migration failed while applying revision 202603260003 against pos_sales_import_row.approval_metadata."
    echo >&2 "[entrypoint] If you hit duplicate column name: approval_metadata, follow README.md -> Runbook: recovering drifted pos_sales_import* tables before Alembic 202603260001 -> If you see duplicate column name: approval_metadata."
    exit 1
fi

# Ensure the database has the initial admin user and settings
python <<'PYTHON'
from seed_data import seed_initial_data
from app import create_app
from app.models import User, Setting

app, _ = create_app([])
with app.app_context():
    needs_seed = (
        User.query.filter_by(is_admin=True).first() is None
        or Setting.query.filter_by(name="GST").first() is None
        or Setting.query.filter_by(name="DEFAULT_TIMEZONE").first() is None
    )
    if needs_seed:
        seed_initial_data()
PYTHON

if [ "$1" = "gunicorn" ]; then
    shift
    exec gunicorn "$@"
fi

exec "$@"
