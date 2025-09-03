import os

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
