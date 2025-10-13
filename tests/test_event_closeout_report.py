from datetime import date
from decimal import Decimal

from app import db
from app.models import (
    Event,
    EventLocation,
    EventLocationTerminalSalesSummary,
    Location,
    Product,
    TerminalSale,
)
from app.routes.report_routes import _compile_event_closeout_report


def test_closeout_report_uses_summary_totals_for_terminal_sales(app):
    with app.app_context():
        location = Location(name="Main Stand")
        product = Product(name="Hot Dog", price=5.0, cost=2.0)
        event = Event(
            name="Sample Event",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            closed=True,
        )

        db.session.add_all([location, product, event])
        db.session.commit()

        event_location = EventLocation(
            event_id=event.id,
            location_id=location.id,
            confirmed=True,
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
        db.session.commit()

        event = db.session.get(Event, event.id)
        report = _compile_event_closeout_report(event)

        location_report = report["locations"][0]
        assert location_report["totals"]["terminal_amount"] == Decimal("23.00")
        assert location_report["totals"]["system_terminal_amount"] == Decimal("10.00")
        assert location_report["totals"]["entered_amount"] == Decimal("23.00")
        assert location_report["totals"]["entered_difference"] == Decimal("-13.00")

        totals = report["totals"]
        assert totals["terminal_amount"] == Decimal("23.00")
        assert totals["system_terminal_amount"] == Decimal("10.00")
        assert totals["entered_amount"] == Decimal("23.00")
        assert totals["entered_difference"] == Decimal("-13.00")
