from datetime import date, datetime

from app import db
from app.models import Customer, Invoice, InvoiceProduct, Location, Product, Transfer, User
from app.services.dashboard_metrics import weekly_transfer_purchase_activity
from tests.utils import login


def _create_basic_sale(user: User, *, when: datetime) -> Invoice:
    customer = Customer(first_name="Casey", last_name="Customer")
    product = Product(name="Espresso", price=5.0, cost=0.0, quantity=0.0)
    invoice = Invoice(id="INV001", customer=customer, creator=user, date_created=when)
    invoice.products.append(
        InvoiceProduct(
            quantity=2,
            product=product,
            product_name=product.name,
            unit_price=5.0,
            line_subtotal=10.0,
            line_gst=0.0,
            line_pst=0.0,
        )
    )

    db.session.add_all([customer, product, invoice])

    return invoice


def test_weekly_activity_includes_sales_totals(app):
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        loc_a = Location(name="Front")
        loc_b = Location(name="Back")
        db.session.add_all([loc_a, loc_b])
        db.session.flush()

        db.session.add(
            Transfer(
                from_location=loc_a,
                to_location=loc_b,
                creator=user,
                date_created=datetime(2024, 1, 9, 12, 0, 0),
            )
        )
        db.session.add(_create_basic_sale(user, when=datetime(2024, 1, 8, 10, 0, 0)))
        db.session.commit()

        activity = weekly_transfer_purchase_activity(weeks=2, today=date(2024, 1, 10))

        target_week = next(
            bucket for bucket in activity if bucket["week_start"] == "2024-01-08"
        )
        assert target_week["sales"] == 1
        assert target_week["sales_total"] == 10.0


def test_dashboard_renders_sales_series(client, app):
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        loc_a = Location(name="North")
        loc_b = Location(name="South")
        db.session.add_all([loc_a, loc_b])
        db.session.flush()

        db.session.add(
            Transfer(
                from_location=loc_a,
                to_location=loc_b,
                creator=user,
                date_created=datetime.utcnow(),
            )
        )
        _create_basic_sale(user, when=datetime.utcnow())
        db.session.commit()

    login(client, "admin@example.com", "adminpass")
    response = client.get("/", follow_redirects=True)
    body = response.data.decode()

    assert '"sales_total":' in body
    assert "$10.00" in body
