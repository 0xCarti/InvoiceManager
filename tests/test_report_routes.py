from datetime import date

from werkzeug.security import generate_password_hash

from app import db
from app.models import Customer, Invoice, InvoiceProduct, Product, User
from tests.utils import login


def setup_invoice(app):
    with app.app_context():
        user = User.query.filter_by(email="report@example.com").first()
        if not user:
            user = User(
                email="report@example.com",
                password=generate_password_hash("pass"),
                active=True,
            )
            db.session.add(user)

        customer = Customer.query.filter_by(first_name="Jane", last_name="Doe").first()
        if not customer:
            customer = Customer(first_name="Jane", last_name="Doe")
            db.session.add(customer)

        product = Product.query.filter_by(name="Widget").first()
        if not product:
            product = Product(name="Widget", price=10.0, cost=5.0)
            db.session.add(product)

        db.session.commit()
        invoice = Invoice.query.get("INVREP001")
        if not invoice:
            invoice = Invoice(
                id="INVREP001",
                user_id=user.id,
                customer_id=customer.id,
                date_created=date(2023, 1, 1),
            )
            db.session.add(invoice)
            db.session.commit()

        has_line_item = (
            InvoiceProduct.query.filter_by(invoice_id=invoice.id, product_id=product.id)
            .first()
            is not None
        )
        if not has_line_item:
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
    login(client, "report@example.com", "pass")
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


def test_purchase_cost_forecast_report(client, app):
    setup_invoice(app)
    login(client, "report@example.com", "pass")

    resp = client.get("/reports/purchase-cost-forecast")
    assert resp.status_code == 200

    resp = client.post(
        "/reports/purchase-cost-forecast",
        data={
            "forecast_period": "7",
            "location_id": "0",
            "purchase_gl_code_ids": ["0"],
            "item_id": "0",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"No forecast data was available" in resp.data
