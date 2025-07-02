import os
from datetime import datetime
from werkzeug.security import generate_password_hash

from app import db
from app.models import User, Customer, Product, Invoice
from tests.test_user_flows import login


def setup_sales(app):
    with app.app_context():
        user = User(email='sales@example.com', password=generate_password_hash('pass'), active=True)
        customer = Customer(first_name='Jane', last_name='Doe')
        product = Product(name='Widget', price=10.0, cost=5.0, quantity=5)
        db.session.add_all([user, customer, product])
        db.session.commit()
        return user.email, customer.id, product.name, product.id


def test_sales_invoice_create_view_delete(client, app):
    email, cust_id, prod_name, prod_id = setup_sales(app)

    with client:
        login(client, email, 'pass')
        resp = client.post('/create_invoice', data={
            'customer': float(cust_id),
            'products': f'{prod_name}?2??'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invoice created successfully' in resp.data

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        assert invoice.products[0].quantity == 2
        assert invoice.id.startswith('JD')
        invoice_id = invoice.id
        product = Product.query.get(prod_id)
        assert product.quantity == 3

    with client:
        login(client, email, 'pass')
        resp = client.get(f'/view_invoice/{invoice_id}')
        assert resp.status_code == 200
        assert str(invoice_id).encode() in resp.data

    with client:
        login(client, email, 'pass')
        resp = client.get(f'/delete_invoice/{invoice_id}', follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Invoice, invoice_id) is None


def test_invoice_survives_product_deletion(client, app):
    email, cust_id, prod_name, prod_id = setup_sales(app)

    with client:
        login(client, email, 'pass')
        resp = client.post('/create_invoice', data={
            'customer': float(cust_id),
            'products': f'{prod_name}?1??'
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        invoice_id = invoice.id

    with client:
        login(client, email, 'pass')
        resp = client.get(f'/products/{prod_id}/delete', follow_redirects=True)
        assert resp.status_code == 200

    with client:
        login(client, email, 'pass')
        resp = client.get(f'/view_invoice/{invoice_id}')
        assert resp.status_code == 200
        assert prod_name.encode() in resp.data
