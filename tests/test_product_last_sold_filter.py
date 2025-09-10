import os
from datetime import datetime, timedelta, date

from app import db
from app.models import (
    Customer,
    Event,
    EventLocation,
    Invoice,
    InvoiceProduct,
    Location,
    Product,
    TerminalSale,
    User,
)
from werkzeug.security import generate_password_hash
from tests.utils import login


def setup_sales_data(app):
    with app.app_context():
        user = User(
            email="sales@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        cust = Customer(first_name="Test", last_name="Customer")
        p_old = Product(name="OldProd", price=1.0, cost=0.5)
        p_recent = Product(name="RecentProd", price=1.0, cost=0.5)
        p_unsold = Product(name="UnsoldProd", price=1.0, cost=0.5)
        loc = Location(name="Loc1")
        event = Event(name="Event1", start_date=date.today(), end_date=date.today())
        ev_loc = EventLocation(event=event, location=loc)
        db.session.add_all([
            user,
            cust,
            p_old,
            p_recent,
            p_unsold,
            loc,
            event,
            ev_loc,
        ])
        db.session.commit()
        inv = Invoice(
            id="INV1",
            user_id=user.id,
            customer_id=cust.id,
            date_created=datetime.utcnow() - timedelta(days=10),
        )
        db.session.add(inv)
        db.session.commit()
        ip = InvoiceProduct(
            invoice_id=inv.id,
            quantity=1,
            product_id=p_old.id,
            product_name=p_old.name,
            unit_price=1,
            line_subtotal=1,
            line_gst=0,
            line_pst=0,
        )
        ts = TerminalSale(
            event_location_id=ev_loc.id,
            product_id=p_recent.id,
            quantity=1,
            sold_at=datetime.utcnow() - timedelta(days=1),
        )
        db.session.add_all([ip, ts])
        db.session.commit()
        return p_old.name, p_recent.name, p_unsold.name


def test_last_sold_before_filter(client, app):
    old_name, recent_name, _ = setup_sales_data(app)
    with client:
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        admin_pass = os.getenv("ADMIN_PASS", "adminpass")
        login(client, admin_email, admin_pass)
        cutoff = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        resp = client.get(f"/products?last_sold_before={cutoff}")
        assert resp.status_code == 200
        assert old_name.encode() in resp.data
        assert recent_name.encode() not in resp.data


def test_include_unsold_products(client, app):
    old_name, recent_name, unsold_name = setup_sales_data(app)
    with client:
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        admin_pass = os.getenv("ADMIN_PASS", "adminpass")
        login(client, admin_email, admin_pass)
        cutoff = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        resp = client.get(
            f"/products?last_sold_before={cutoff}&include_unsold=1"
        )
        assert resp.status_code == 200
        assert old_name.encode() in resp.data
        assert unsold_name.encode() in resp.data
        assert recent_name.encode() not in resp.data
