from werkzeug.security import generate_password_hash

from app import db
from app.models import Item, ItemUnit, User, Vendor
from tests.utils import login


def test_purchase_order_page_has_quick_add(client, app):
    with app.app_context():
        user = User(
            email="poquick@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        vendor = Vendor(first_name="Quick", last_name="Vendor")
        db.session.add_all([user, vendor])
        db.session.commit()
    with client:
        login(client, "poquick@example.com", "pass")
        resp = client.get("/purchase_orders/create")
        assert resp.status_code == 200
        assert b'id="quick-add-item"' in resp.data


def test_quick_add_item_endpoint(client, app):
    with app.app_context():
        user = User(
            email="apiquick@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        db.session.add(user)
        db.session.commit()
    with client:
        login(client, "apiquick@example.com", "pass")
        resp = client.post(
            "/items/quick_add", json={"name": "FastItem", "base_unit": "each"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "FastItem"
        item_id = data["id"]
    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item is not None
        assert item.base_unit == "each"
        unit = ItemUnit.query.filter_by(item_id=item_id).first()
        assert unit is not None
        assert unit.name == "each"
