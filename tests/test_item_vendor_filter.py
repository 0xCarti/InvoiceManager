from datetime import date

from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    Item,
    PurchaseOrder,
    PurchaseOrderItem,
    User,
    Vendor,
)
from tests.utils import login


def setup_data(app):
    with app.app_context():
        user = User(
            email="vendorfilter@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        vendor1 = Vendor(first_name="Sup", last_name="One")
        vendor2 = Vendor(first_name="Sup", last_name="Two")
        item1 = Item(name="A0", base_unit="each")
        item2 = Item(name="B0", base_unit="each")
        db.session.add_all([user, vendor1, vendor2, item1, item2])
        db.session.commit()

        po = PurchaseOrder(
            vendor_id=vendor1.id,
            user_id=user.id,
            vendor_name=f"{vendor1.first_name} {vendor1.last_name}",
            order_date=date.today(),
            expected_date=date.today(),
        )
        db.session.add(po)
        db.session.commit()

        db.session.add(
            PurchaseOrderItem(purchase_order_id=po.id, item_id=item1.id, quantity=1)
        )
        db.session.commit()
        return user.email, vendor1.id


def test_view_items_filter_by_vendor(client, app):
    email, vendor_id = setup_data(app)
    with client:
        login(client, email, "pass")
        resp = client.get(f"/items?vendor_id={vendor_id}")
        assert resp.status_code == 200
        assert b"A0" in resp.data
        assert b"B0" not in resp.data
        assert b"Filtering by Supplier" in resp.data

