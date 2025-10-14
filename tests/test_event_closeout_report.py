from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    Event,
    EventLocation,
    EventLocationTerminalSalesSummary,
    EventStandSheetItem,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    Product,
    ProductRecipeItem,
    TerminalSale,
    User,
)
from app.routes.report_routes import _compile_event_closeout_report
from tests.utils import login


def test_closeout_report_uses_summary_totals_for_terminal_sales(app):
    with app.app_context():
        location = Location(name="Main Stand")
        item = Item(name="591ml Pepsi", base_unit="each")
        product = Product(name="Hot Dog", price=5.0, cost=2.0)
        event = Event(
            name="Sample Event",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            closed=True,
            estimated_sales=Decimal("40.00"),
        )

        db.session.add_all([location, product, item, event])
        db.session.commit()

        unit = ItemUnit(
            item_id=item.id,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        recipe = ProductRecipeItem(
            product_id=product.id,
            item_id=item.id,
            unit_id=unit.id,
            quantity=1,
            countable=True,
        )
        location.products.append(product)
        stand_item = LocationStandItem(
            location_id=location.id,
            item_id=item.id,
            expected_count=0,
        )
        db.session.add_all([unit, recipe, stand_item])
        db.session.commit()

        event_location = EventLocation(
            event_id=event.id,
            location_id=location.id,
            confirmed=True,
            notes="Final stand sheet note",
        )
        db.session.add(event_location)
        db.session.commit()

        db.session.add(
            TerminalSale(
                event_location_id=event_location.id,
                product_id=product.id,
                quantity=2.0,
            )
        )

        summary = EventLocationTerminalSalesSummary(
            event_location_id=event_location.id,
            source_location="Register 1",
            total_quantity=2.0,
            total_amount=23.0,
            variance_details={
                "products": [
                    {
                        "product_id": product.id,
                        "product_name": product.name,
                        "quantity": 2.0,
                        "file_amount": 18.0,
                        "file_prices": [9.0],
                        "app_price": 5.0,
                        "sales_location": "Register 1",
                    }
                ],
                "price_mismatches": [],
                "menu_issues": [],
                "unmapped_products": [
                    {
                        "product_name": "Extra Sauce",
                        "quantity": 0.0,
                        "file_amount": 5.0,
                        "file_prices": [5.0],
                        "sales_location": "Register 1",
                    }
                ],
            },
        )
        db.session.add(summary)

        sheet = EventStandSheetItem(
            event_location_id=event_location.id,
            item_id=item.id,
            opening_count=10,
            transferred_in=5,
            transferred_out=3,
            adjustments=0,
            eaten=1,
            spoiled=1,
            closing_count=0,
        )
        db.session.add(sheet)
        db.session.commit()

        event = db.session.get(Event, event.id)
        report = _compile_event_closeout_report(event)

        location_report = report["locations"][0]
        assert location_report["totals"]["terminal_amount"] == Decimal("23.00")
        assert location_report["totals"]["system_terminal_amount"] == Decimal("10.00")
        assert location_report["totals"]["entered_amount"] == Decimal("23.00")
        assert location_report["totals"]["entered_difference"] == Decimal("-13.00")
        assert location_report["totals"]["physical_quantity"] == 10.0
        assert location_report["totals"]["physical_amount"] == Decimal("50.00")
        assert location_report["totals"]["physical_vs_terminal_amount"] == Decimal("27.00")

        totals = report["totals"]
        assert totals["terminal_amount"] == Decimal("23.00")
        assert totals["system_terminal_amount"] == Decimal("10.00")
        assert totals["entered_amount"] == Decimal("23.00")
        assert totals["entered_difference"] == Decimal("-13.00")
        assert totals["physical_quantity"] == 10.0
        assert totals["physical_amount"] == Decimal("50.00")
        assert totals["physical_vs_terminal_amount"] == Decimal("27.00")

        snapshot = report["snapshot"]
        assert snapshot["estimated_sales"] == Decimal("40.00")
        assert snapshot["terminal_vs_estimate"] == Decimal("-17.00")
        assert snapshot["physical_vs_estimate"] == Decimal("10.00")


def test_close_event_preserves_manual_terminal_sales(app, client):
    with app.app_context():
        location = Location(name="Manual Stand")
        product = Product(name="Manual Item", price=7.5, cost=3.0)
        event = Event(
            name="Manual Sales Event",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 2),
            estimated_sales=Decimal("100.00"),
        )

        db.session.add_all([location, product, event])
        db.session.commit()

        event_location = EventLocation(
            event_id=event.id,
            location_id=location.id,
            confirmed=False,
        )
        db.session.add(event_location)
        db.session.commit()

        db.session.add(
            TerminalSale(
                event_location_id=event_location.id,
                product_id=product.id,
                quantity=3.0,
            )
        )
        db.session.commit()

        user = User(
            email="eventuser@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        db.session.add(user)
        db.session.commit()

        event_id = event.id
        event_location_id = event_location.id
        product_id = product.id
        user_id = user.id

    login_response = login(client, "eventuser@example.com", "pass")
    assert login_response.status_code == 200
    assert b"Invalid email or password" not in login_response.data
    with client.session_transaction() as session_data:
        session_data["_user_id"] = str(user_id)
        session_data["_fresh"] = True

    confirm_response = client.post(
        f"/events/{event_id}/locations/{event_location_id}/confirm",
        data={"submit": "Confirm", "csrf_token": ""},
        follow_redirects=False,
    )
    assert confirm_response.status_code == 302
    assert "/events" in confirm_response.headers.get("Location", "")

    with app.app_context():
        el = db.session.get(EventLocation, event_location_id)
        assert el.confirmed is True
        summary = el.terminal_sales_summary
        assert summary is not None
        assert summary.total_quantity == pytest.approx(3.0)
        assert summary.total_amount == pytest.approx(22.5)

    close_response = client.get(
        f"/events/{event_id}/close", follow_redirects=True
    )
    assert close_response.status_code == 200

    with app.app_context():
        event = db.session.get(Event, event_id)
        el = db.session.get(EventLocation, event_location_id)
        assert event.closed is True
        assert len(el.terminal_sales) == 1
        sale = el.terminal_sales[0]
        assert sale.product_id == product_id
        assert sale.quantity == pytest.approx(3.0)

        summary = el.terminal_sales_summary
        assert summary is not None
        assert summary.total_quantity == pytest.approx(3.0)
        assert summary.total_amount == pytest.approx(22.5)
