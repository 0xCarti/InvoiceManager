from datetime import date

import pytest

from app import db
from app.models import (
    Event,
    EventLocation,
    EventLocationTerminalSalesSummary,
    Location,
    Product,
    TerminalSale,
)
from app.routes.event_routes import _apply_pending_sales


def test_apply_pending_sales_replaces_previous_entries(app):
    with app.app_context():
        event = Event(
            name="Cleanup Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Main Stand")
        event_location = EventLocation(event=event, location=location)
        product_one = Product(name="Popcorn", price=5.0, cost=2.0)
        product_two = Product(name="Soda", price=3.0, cost=1.0)

        db.session.add_all(
            [event, location, event_location, product_one, product_two]
        )
        db.session.commit()

        first_sales = [
            {
                "event_location_id": event_location.id,
                "product_id": product_one.id,
                "quantity": 10.0,
                "product_name": product_one.name,
            },
            {
                "event_location_id": event_location.id,
                "product_id": product_two.id,
                "quantity": 4.0,
                "product_name": product_two.name,
            },
        ]
        first_totals = [
            {
                "event_location_id": event_location.id,
                "source_location": "Register A",
                "total_quantity": 14.0,
                "total_amount": 100.0,
                "variance_details": {
                    "products": [
                        {
                            "product_id": product_one.id,
                            "product_name": product_one.name,
                            "quantity": 10.0,
                            "file_amount": 70.0,
                            "file_prices": [7.0],
                        }
                    ]
                },
            }
        ]

        _apply_pending_sales(first_sales, first_totals)
        db.session.commit()

        initial_sales = TerminalSale.query.filter_by(
            event_location_id=event_location.id
        ).all()
        assert {sale.product_id for sale in initial_sales} == {
            product_one.id,
            product_two.id,
        }

        second_sales = [
            {
                "event_location_id": event_location.id,
                "product_id": product_one.id,
                "quantity": 7.0,
                "product_name": product_one.name,
            }
        ]
        second_totals = [
            {
                "event_location_id": event_location.id,
                "source_location": "Register A",
                "total_quantity": 7.0,
                "total_amount": 49.0,
            }
        ]

        _apply_pending_sales(second_sales, second_totals)
        db.session.commit()

        remaining_sales = TerminalSale.query.filter_by(
            event_location_id=event_location.id
        ).all()
        assert [sale.product_id for sale in remaining_sales] == [product_one.id]
        assert remaining_sales[0].quantity == pytest.approx(7.0)

        summary = EventLocationTerminalSalesSummary.query.filter_by(
            event_location_id=event_location.id
        ).one()
        assert summary.total_quantity == pytest.approx(7.0)
        assert summary.total_amount == pytest.approx(49.0)
