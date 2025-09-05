import os
import sys

import pytest

from flask_migrate import upgrade

from app import create_app, create_admin_user, db
from app.models import GLCode, Setting

# Ensure the app package is importable when tests change directories
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)


@pytest.fixture
def app(tmp_path):
    os.environ.setdefault("SECRET_KEY", "testsecret")
    os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
    os.environ.setdefault("ADMIN_PASS", "adminpass")
    os.environ.setdefault("SMTP_HOST", "localhost")
    os.environ.setdefault("SMTP_PORT", "25")
    os.environ.setdefault("SMTP_USERNAME", "user")
    os.environ.setdefault("SMTP_PASSWORD", "pass")
    os.environ.setdefault("SMTP_SENDER", "test@example.com")

    # Ensure a clean database for each test within the temp directory
    db_path = tmp_path / "inventory.db"
    if db_path.exists():
        os.remove(db_path)

    cwd = os.getcwd()
    os.chdir(tmp_path)
    app, _ = create_app(["--demo"])
    os.chdir(cwd)

    app.config.update({"TESTING": True, "WTF_CSRF_ENABLED": False})

    with app.app_context():
        try:
            upgrade()
        except Exception:
            db.session.rollback()
        db.create_all()
        create_admin_user()
        if Setting.query.filter_by(name="GST").count() == 0:
            db.session.add(Setting(name="GST", value=""))
        if Setting.query.filter_by(name="DEFAULT_TIMEZONE").count() == 0:
            db.session.add(Setting(name="DEFAULT_TIMEZONE", value="UTC"))
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def gl_codes(app):
    with app.app_context():
        if GLCode.query.count() == 0:
            db.session.add_all([GLCode(code="4000"), GLCode(code="5000")])
            db.session.commit()
