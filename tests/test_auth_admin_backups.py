import os
import shutil

from app.utils.backup import RestoreCompatibilityResult
from tests.utils import login


def test_restore_backup_file_compatible_metadata_flashes_success(
    client, app, monkeypatch
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    with app.app_context():
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace(
            "sqlite:///", "", 1
        )
        backup_path = os.path.join(app.config["BACKUP_FOLDER"], "compatible.db")
        shutil.copyfile(db_path, backup_path)

    monkeypatch.setattr(
        "app.routes.auth_routes.validate_restored_backup_compatibility",
        lambda: RestoreCompatibilityResult(compatible=True, issues=[]),
    )

    with client:
        login(client, admin_email, admin_pass)
        response = client.post(
            "/controlpanel/backups/restore/compatible.db",
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert b"Backup restored from compatible.db" in response.data
    assert b"Incompatible backup" not in response.data


def test_restore_backup_file_incompatible_metadata_shows_failure_flash(
    client, app, monkeypatch
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    with app.app_context():
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace(
            "sqlite:///", "", 1
        )
        backup_path = os.path.join(app.config["BACKUP_FOLDER"], "incompatible.db")
        shutil.copyfile(db_path, backup_path)

    monkeypatch.setattr(
        "app.routes.auth_routes.validate_restored_backup_compatibility",
        lambda: RestoreCompatibilityResult(
            compatible=False, issues=["missing marker"]
        ),
    )

    with client:
        login(client, admin_email, admin_pass)
        response = client.post(
            "/controlpanel/backups/restore/incompatible.db",
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert b"Incompatible backup" in response.data
    assert b"Backup restored from incompatible.db" not in response.data
