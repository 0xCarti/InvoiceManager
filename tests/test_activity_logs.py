import os

from flask import url_for
from werkzeug.security import generate_password_hash

from app import db
from app.models import ActivityLog, User
from tests.utils import login


def create_log(app):
    with app.app_context():
        user = User(
            email="log@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        db.session.add(user)
        db.session.commit()
        log = ActivityLog(user_id=user.id, activity="Did something")
        db.session.add(log)
        db.session.commit()
        return log.activity


def test_admin_can_view_activity_logs(client, app):
    text = create_log(app)
    with app.app_context():
        with app.test_request_context():
            expected = url_for("admin.activity_logs")

    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")
    with client:
        login(client, admin_email, admin_pass)
        resp = client.get(expected, follow_redirects=True)
        assert resp.status_code == 200
        assert text.encode() in resp.data


def test_non_admin_forbidden_from_activity_logs(client, app):
    with app.app_context():
        user = User(
            email="normal@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        db.session.add(user)
        db.session.commit()

    with client:
        login(client, "normal@example.com", "pass")
        resp = client.get("/controlpanel/activity")
        assert resp.status_code == 403
