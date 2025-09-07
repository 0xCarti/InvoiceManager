from werkzeug.security import generate_password_hash

from app import db
from app.models import GLCode, Item, User
from tests.utils import login


def setup_data(app):
    with app.app_context():
        user = User(
            email="filter@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        gl1 = GLCode(code="1000", description="Food")
        gl2 = GLCode(code="2000", description="Drink")
        db.session.add_all([user, gl1, gl2])
        db.session.commit()
        for i in range(5):
            db.session.add(
                Item(name=f"A{i}", base_unit="each", gl_code_id=gl1.id)
            )
        db.session.add(Item(name="B0", base_unit="each", gl_code_id=gl2.id))
        db.session.commit()
        return user.email, gl1.id, gl2.id, gl1.code


def test_view_items_filter_by_gl_code(client, app):
    email, gl1_id, _, gl_code = setup_data(app)
    with client:
        login(client, email, "pass")
        resp = client.get(f"/items?gl_code_id={gl1_id}")
        assert resp.status_code == 200
        assert b"A0" in resp.data
        assert b"B0" not in resp.data
        assert b"Filtering by GL Code" in resp.data
        assert gl_code.encode() in resp.data


def test_view_items_filter_by_multiple_gl_codes(client, app):
    email, gl1_id, gl2_id, _ = setup_data(app)
    with client:
        login(client, email, "pass")
        resp = client.get(f"/items?gl_code_id={gl1_id}&gl_code_id={gl2_id}")
        assert resp.status_code == 200
        assert b"A0" in resp.data
        assert b"B0" in resp.data
        assert b"Filtering by GL Code" in resp.data
