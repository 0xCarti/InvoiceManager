from datetime import date

from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    Customer,
    GLCode,
    Invoice,
    InvoiceProduct,
    Item,
    Location,
    Product,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    User,
    Vendor,
)
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

        sales_gl_4000 = GLCode.query.filter_by(code="4000").first()
        if not sales_gl_4000:
            sales_gl_4000 = GLCode(code="4000", description="Food Sales")
            db.session.add(sales_gl_4000)

        sales_gl_4010 = GLCode.query.filter_by(code="4010").first()
        if not sales_gl_4010:
            sales_gl_4010 = GLCode(code="4010", description="Beverage Sales")
            db.session.add(sales_gl_4010)

        product = Product.query.filter_by(name="Widget").first()
        if not product:
            product = Product(
                name="Widget",
                price=10.0,
                cost=5.0,
                sales_gl_code=sales_gl_4000,
            )
            db.session.add(product)
        else:
            product.sales_gl_code = sales_gl_4000

        second_product = Product.query.filter_by(name="Gadget").first()
        if not second_product:
            second_product = Product(
                name="Gadget",
                price=8.0,
                cost=3.0,
                sales_gl_code=sales_gl_4010,
            )
            db.session.add(second_product)
        else:
            second_product.sales_gl_code = sales_gl_4010

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

        has_widget = (
            InvoiceProduct.query.filter_by(invoice_id=invoice.id, product_id=product.id)
            .first()
            is not None
        )
        if not has_widget:
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

        has_gadget = (
            InvoiceProduct.query.filter_by(
                invoice_id=invoice.id, product_id=second_product.id
            )
            .first()
            is not None
        )
        if not has_gadget:
            db.session.add(
                InvoiceProduct(
                    invoice_id=invoice.id,
                    quantity=1,
                    product_id=second_product.id,
                    product_name=second_product.name,
                    unit_price=second_product.price,
                    line_subtotal=8,
                    line_gst=0,
                    line_pst=0,
                )
            )
            db.session.commit()
        return customer.id


def setup_purchase_invoice(app):
    with app.app_context():
        user = User.query.filter_by(email="purchasereport@example.com").first()
        if not user:
            user = User(
                email="purchasereport@example.com",
                password=generate_password_hash("pass"),
                active=True,
            )
            db.session.add(user)

        vendor = Vendor.query.filter_by(first_name="Report", last_name="Vendor").first()
        if not vendor:
            vendor = Vendor(first_name="Report", last_name="Vendor")
            db.session.add(vendor)

        location = Location.query.filter_by(name="Report Location").first()
        if not location:
            location = Location(name="Report Location")
            db.session.add(location)

        item = Item.query.filter_by(name="Purchase Widget").first()
        if not item:
            item = Item(name="Purchase Widget", base_unit="each", cost=3.0)
            db.session.add(item)

        db.session.commit()

        po = PurchaseOrder.query.filter_by(
            vendor_id=vendor.id,
            user_id=user.id,
            vendor_name=f"{vendor.first_name} {vendor.last_name}",
        ).first()
        if not po:
            po = PurchaseOrder(
                vendor_id=vendor.id,
                user_id=user.id,
                vendor_name=f"{vendor.first_name} {vendor.last_name}",
                order_date=date(2023, 1, 1),
                expected_date=date(2023, 1, 1),
            )
            db.session.add(po)
            db.session.commit()

        invoice = PurchaseInvoice.query.filter_by(
            invoice_number="PINVREP001"
        ).first()
        if not invoice:
            invoice = PurchaseInvoice(
                purchase_order_id=po.id,
                user_id=user.id,
                location_id=location.id,
                location_name=location.name,
                vendor_name=f"{vendor.first_name} {vendor.last_name}",
                received_date=date(2023, 1, 15),
                invoice_number="PINVREP001",
                gst=0,
                pst=0,
                delivery_charge=0,
            )
            db.session.add(invoice)
            db.session.commit()

        line_exists = (
            PurchaseInvoiceItem.query.filter_by(
                invoice_id=invoice.id, item_id=item.id
            ).first()
            is not None
        )
        if not line_exists:
            db.session.add(
                PurchaseInvoiceItem(
                    invoice_id=invoice.id,
                    item_id=item.id,
                    item_name=item.name,
                    quantity=5,
                    cost=3.0,
                )
            )
            db.session.commit()

        return user.email, invoice.received_date, item.name


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
    assert b"Gadget" in resp.data

    with app.app_context():
        widget = Product.query.filter_by(name="Widget").first()
        widget_gl = widget.sales_gl_code_id

    resp = client.post(
        "/reports/product-sales",
        data={
            "start_date": "2022-12-31",
            "end_date": "2023-12-31",
            "products": [str(widget.id)],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Widget" in resp.data
    assert b"Gadget" not in resp.data

    resp = client.post(
        "/reports/product-sales",
        data={
            "start_date": "2022-12-31",
            "end_date": "2023-12-31",
            "gl_codes": [str(widget_gl)],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Widget" in resp.data
    assert b"Gadget" not in resp.data


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


def test_purchase_inventory_summary_report(client, app):
    email, received_date, item_name = setup_purchase_invoice(app)
    login(client, email, "pass")

    resp = client.get("/reports/purchase-inventory-summary")
    assert resp.status_code == 200

    resp = client.post(
        "/reports/purchase-inventory-summary",
        data={
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Purchase Inventory Summary" in resp.data
    assert item_name.encode() in resp.data
    assert b"$15.00" in resp.data
