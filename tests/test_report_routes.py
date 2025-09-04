from datetime import date

from werkzeug.security import generate_password_hash

from app import db
from app.models import Customer, Invoice, InvoiceProduct, Product, User


def setup_invoice(app):
    with app.app_context():
        user = User(
            email="report@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        customer = Customer(first_name="Jane", last_name="Doe")
        product = Product(name="Widget", price=10.0, cost=5.0)
        db.session.add_all([user, customer, product])
        db.session.commit()
        invoice = Invoice(
            id="INVREP001",
            user_id=user.id,
            customer_id=customer.id,
            date_created=date(2023, 1, 1),
        )
        db.session.add(invoice)
        db.session.commit()
        db.session.add(
            InvoiceProduct(
                invoice_id=invoice.id,
                quantity=2,
                product_id=product.id,
                product_name=product.name,
                unit_price=product.price,
                line_subtotal=20,
                line_gst=0,
                line_pst=0,
            )
        )
        db.session.commit()
        return customer.id


def test_vendor_and_sales_reports(client, app):
    cid = setup_invoice(app)
    resp = client.get("/reports/vendor-invoices")
    assert resp.status_code == 200
    resp = client.post(
        "/reports/vendor-invoices",
        data={
            "customer": [str(cid)],
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"INVREP001" in resp.data
    resp = client.get("/reports/product-sales")
    assert resp.status_code == 200
    resp = client.post(
        "/reports/product-sales",
        data={"start_date": "2022-12-31", "end_date": "2023-12-31"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Widget" in resp.data
