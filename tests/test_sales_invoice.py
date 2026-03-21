import os
from datetime import datetime
import re

import pytest
from werkzeug.security import generate_password_hash

from app import db
from app.models import Customer, Invoice, Product, User
from tests.utils import login


def setup_sales(app):
    with app.app_context():
        user = User(
            email="sales@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        customer = Customer(first_name="Jane", last_name="Doe")
        product = Product(name="Widget", price=10.0, cost=5.0, quantity=5)
        db.session.add_all([user, customer, product])
        db.session.commit()
        return user.email, customer.id, product.name, product.id


def test_sales_invoice_create_view_delete(client, app):
    email, cust_id, prod_name, prod_id = setup_sales(app)

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/create_invoice",
            data={"customer": float(cust_id), "products": f"{prod_name}?2??"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invoice created successfully" in resp.data

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        assert invoice.is_paid is False
        assert invoice.paid_at is None
        assert invoice.products[0].quantity == 2
        assert invoice.id.startswith("JD")
        invoice_id = invoice.id
        product = Product.query.get(prod_id)
        assert product.quantity == 3

    with client:
        login(client, email, "pass")
        resp = client.get(f"/view_invoice/{invoice_id}")
        assert resp.status_code == 200
        assert str(invoice_id).encode() in resp.data

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/delete_invoice/{invoice_id}", follow_redirects=True
        )
        assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Invoice, invoice_id) is None


def test_invoice_survives_product_deletion(client, app):
    email, cust_id, prod_name, prod_id = setup_sales(app)

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/create_invoice",
            data={"customer": float(cust_id), "products": f"{prod_name}?1??"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        invoice_id = invoice.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/products/{prod_id}/delete", follow_redirects=True
        )
        assert resp.status_code == 200

    with client:
        login(client, email, "pass")
        resp = client.get(f"/view_invoice/{invoice_id}")
        assert resp.status_code == 200
        assert prod_name.encode() in resp.data


def test_sales_invoice_returns(client, app):
    email, cust_id, prod_name, prod_id = setup_sales(app)

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/create_invoice",
            data={"customer": float(cust_id), "products": f"{prod_name}?-2??"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        assert invoice.products[0].quantity == -2
        assert invoice.total == pytest.approx(-22.4)
        product = Product.query.get(prod_id)
        assert product.quantity == 7


def test_delete_invoice_route_still_accepts_post_from_list_form(client, app):
    email, cust_id, prod_name, _ = setup_sales(app)

    with client:
        login(client, email, "pass")
        create_resp = client.post(
            "/create_invoice",
            data={"customer": float(cust_id), "products": f"{prod_name}?1??"},
            follow_redirects=True,
        )
        assert create_resp.status_code == 200

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        invoice_id = invoice.id

    with client:
        login(client, email, "pass")
        list_resp = client.get("/view_invoices", follow_redirects=True)
        assert list_resp.status_code == 200
        html = list_resp.get_data(as_text=True)
        assert f'action="/delete_invoice/{invoice_id}"' in html
        assert 'class="js-confirm-delete-invoice"' in html
        assert 'method="post"' in html

        delete_resp = client.post(
            f"/delete_invoice/{invoice_id}", follow_redirects=True
        )
        assert delete_resp.status_code == 200
        assert b"Invoice deleted successfully!" in delete_resp.data

    with app.app_context():
        assert db.session.get(Invoice, invoice_id) is None


def test_mark_invoice_paid_and_unpaid_endpoints_update_payment_state(client, app):
    email, cust_id, prod_name, _ = setup_sales(app)

    with client:
        login(client, email, "pass")
        create_resp = client.post(
            "/create_invoice",
            data={"customer": float(cust_id), "products": f"{prod_name}?1??"},
            follow_redirects=True,
        )
        assert create_resp.status_code == 200

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        invoice_id = invoice.id
        assert invoice.is_paid is False
        assert invoice.paid_at is None

    with client:
        login(client, email, "pass")
        mark_paid_resp = client.post(
            f"/invoice/{invoice_id}/mark-paid", follow_redirects=True
        )
        assert mark_paid_resp.status_code == 200

    with app.app_context():
        paid_invoice = db.session.get(Invoice, invoice_id)
        assert paid_invoice is not None
        assert paid_invoice.is_paid is True
        assert paid_invoice.paid_at is not None

    with client:
        login(client, email, "pass")
        mark_unpaid_resp = client.post(
            f"/invoice/{invoice_id}/mark-unpaid", follow_redirects=True
        )
        assert mark_unpaid_resp.status_code == 200

    with app.app_context():
        unpaid_invoice = db.session.get(Invoice, invoice_id)
        assert unpaid_invoice is not None
        assert unpaid_invoice.is_paid is False
        assert unpaid_invoice.paid_at is None


def test_view_invoices_shows_payment_status_text(client, app):
    email, cust_id, prod_name, _ = setup_sales(app)

    with client:
        login(client, email, "pass")
        create_resp = client.post(
            "/create_invoice",
            data={"customer": float(cust_id), "products": f"{prod_name}?1??"},
            follow_redirects=True,
        )
        assert create_resp.status_code == 200

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        invoice_id = invoice.id

    with client:
        login(client, email, "pass")
        list_resp = client.get("/view_invoices", follow_redirects=True)
        assert list_resp.status_code == 200
        html = list_resp.get_data(as_text=True)
        assert re.search(rf">\s*{invoice_id}\s*<", html)
        assert "badge text-bg-warning" in html
        assert re.search(r">\s*Unpaid\s*<", html)

    with client:
        login(client, email, "pass")
        client.post(f"/invoice/{invoice_id}/mark-paid", follow_redirects=True)
        paid_list_resp = client.get("/view_invoices", follow_redirects=True)
        assert paid_list_resp.status_code == 200
        paid_html = paid_list_resp.get_data(as_text=True)
        assert "badge text-bg-success" in paid_html
        assert re.search(r">\s*Paid\s*<", paid_html)
