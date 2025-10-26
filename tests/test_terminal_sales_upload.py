import json
import os
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
from app.utils.pos_import import group_terminal_sales_rows
from tests.utils import login


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


@pytest.fixture
def terminal_sales_net_only_rows():
    return [
        {
            "location": "Main Stand",
            "product": "Popcorn",
            "quantity": 10.0,
            "net_including_tax_total": 95.0,
            "discount_total": 5.0,
        }
    ]


def test_apply_pending_sales_uses_net_total_when_amount_missing(
    app, terminal_sales_net_only_rows
):
    with app.app_context():
        event = Event(
            name="Net Total Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Main Stand")
        event_location = EventLocation(event=event, location=location)
        product = Product(name="Popcorn", price=10.0, cost=4.0)

        db.session.add_all([event, location, event_location, product])
        db.session.commit()

        grouped = group_terminal_sales_rows(terminal_sales_net_only_rows)
        location_summary = grouped["Main Stand"]
        net_total = sum(
            row.get("net_including_tax_total", 0.0)
            for row in terminal_sales_net_only_rows
        )
        discount_total = sum(
            row.get("discount_total") or 0.0
            for row in terminal_sales_net_only_rows
        )
        expected_total = net_total + discount_total

        pending_sales = [
            {
                "event_location_id": event_location.id,
                "product_id": product.id,
                "product_name": product.name,
                "quantity": terminal_sales_net_only_rows[0]["quantity"],
            }
        ]
        pending_totals = [
            {
                "event_location_id": event_location.id,
                "source_location": "Main Stand",
                "total_quantity": location_summary.get("total"),
                "total_amount": location_summary.get("total_amount"),
                "net_including_tax_total": location_summary.get(
                    "net_including_tax_total"
                ),
                "discount_total": location_summary.get("discount_total"),
                "variance_details": None,
            }
        ]

        _apply_pending_sales(pending_sales, pending_totals)
        db.session.commit()

        summary = EventLocationTerminalSalesSummary.query.filter_by(
            event_location_id=event_location.id
        ).one()
        assert summary.total_amount == pytest.approx(expected_total)


def test_terminal_sales_stays_on_products_until_finish(app, client):
    with app.app_context():
        event = Event(
            name="Terminal Test Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Main Stand")
        event_location = EventLocation(event=event, location=location)
        product = Product(name="Bottled Water", price=3.5, cost=1.0)
        db.session.add_all([event, location, event_location, product])
        db.session.commit()

        payload = json.dumps(
            {
                "rows": [
                    {
                        "location": location.name,
                        "product": product.name,
                        "quantity": 2,
                        "price": float(product.price),
                    }
                ],
                "filename": "terminal.xlsx",
            }
        )

        mapping_field = f"mapping-{event_location.id}"
        event_id = event.id
        event_location_id = event_location.id
        location_name = location.name
        product_id = product.id

    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    with client:
        login_response = login(client, admin_email, admin_pass)
        assert login_response.status_code == 200
        assert login_response.request.path != "/auth/login"

        response = client.post(
            f"/events/{event_id}/terminal-sales",
            data={
                "step": "map",
                "payload": payload,
                "stage": "locations",
                mapping_field: location_name,
                "navigate": "next",
            },
        )

        assert response.status_code == 200
        body = response.data.decode()
        assert 'name="stage" value="products"' in body
        assert (
            "All products in the uploaded file have been matched automatically."
            in body
        )
        assert 'data-role="toggle-product-preview"' in body
        assert 'data-role="product-mapping-preview"' in body
        assert f"(ID: {product_id})" in body

        with app.app_context():
            assert TerminalSale.query.count() == 0

        finish_response = client.post(
            f"/events/{event_id}/terminal-sales",
            data={
                "step": "map",
                "payload": payload,
                "stage": "products",
                mapping_field: location_name,
                "navigate": "finish",
            },
            follow_redirects=False,
        )

        assert finish_response.status_code == 302
        assert finish_response.headers["Location"].endswith(f"/events/{event_id}")

    with app.app_context():
        sales = TerminalSale.query.filter_by(
            event_location_id=event_location_id
        ).all()
        assert len(sales) == 1
        assert sales[0].product_id == product_id
