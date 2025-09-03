from datetime import datetime

from werkzeug.security import generate_password_hash

from app import db
from app.models import Customer, Invoice, User
from tests.utils import login


def setup_invoices(app):
    with app.app_context():
        user = User(
            email="inv@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        c1 = Customer(first_name="Alpha", last_name="One")
        c2 = Customer(first_name="Beta", last_name="Two")
        db.session.add_all([user, c1, c2])
        db.session.commit()

        i1 = Invoice(
            id="INV1",
            user_id=user.id,
            customer_id=c1.id,
            date_created=datetime(2023, 1, 1),
        )
        i2 = Invoice(
            id="INV2",
            user_id=user.id,
            customer_id=c2.id,
            date_created=datetime(2023, 2, 1),
        )
        i3 = Invoice(
            id="INV3",
            user_id=user.id,
            customer_id=c1.id,
            date_created=datetime(2023, 3, 1),
        )
        db.session.add_all([i1, i2, i3])
        db.session.commit()

        return user.email, c1.id, c2.id


def test_filter_by_invoice_id(client, app):
    user_email, c1_id, c2_id = setup_invoices(app)
    with client:
        login(client, user_email, "pass")
        response = client.get(
            "/view_invoices?invoice_id=INV2",
            follow_redirects=True,
        )
        assert b"INV2" in response.data
        assert b"INV1" not in response.data
        assert b"INV3" not in response.data


def test_filter_by_customer(client, app):
    user_email, c1_id, c2_id = setup_invoices(app)
    with client:
        login(client, user_email, "pass")
        response = client.get(
            f"/view_invoices?customer_id={c1_id}",
            follow_redirects=True,
        )
        assert b"INV1" in response.data
        assert b"INV3" in response.data
        assert b"INV2" not in response.data


def test_filter_by_date_range(client, app):
    user_email, c1_id, c2_id = setup_invoices(app)
    with client:
        login(client, user_email, "pass")
        response = client.get(
            "/view_invoices?start_date=2023-02-01&end_date=2023-03-01",
            follow_redirects=True,
        )
        assert b"INV1" not in response.data
        assert b"INV2" in response.data
        assert b"INV3" in response.data
