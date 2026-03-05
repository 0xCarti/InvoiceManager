import os

from app import db
from app.models import User
from tests.utils import login


def test_navbar_has_separate_admin_section(client, app):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")
    with client:
        login(client, admin_email, admin_pass)
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert '<ul class="navbar-nav flex-row me-auto">' in html
        assert '<ul class="navbar-nav flex-row ms-auto">' in html


def test_navbar_renders_when_favorite_endpoint_is_missing(
    client, app, monkeypatch
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    monkeypatch.setattr(
        User,
        "get_favorites",
        lambda self: ["missing.endpoint", "transfer.view_transfers"],
    )

    with client:
        login(client, admin_email, admin_pass)
        response = client.get("/")

    assert response.status_code == 200
    html = response.data.decode()
    assert "Transfers" in html
    assert "missing.endpoint" not in html
