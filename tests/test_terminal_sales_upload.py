import json
import os
import re
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
from app.routes.event_routes import _apply_pending_sales, _apply_resolution_actions
from app.utils.pos_import import (
    derive_terminal_sales_quantity,
    parse_terminal_sales_number,
    group_terminal_sales_rows,
)
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


def test_apply_pending_sales_leaves_location_menu_unchanged(app):
    with app.app_context():
        event = Event(
            name="Menu Hold Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Suite Club")
        event_location = EventLocation(event=event, location=location)
        product = Product(name="Club Sandwich", price=12.0, cost=5.0)

        db.session.add_all([event, location, event_location, product])
        db.session.commit()

        pending_sales = [
            {
                "event_location_id": event_location.id,
                "product_id": product.id,
                "product_name": product.name,
                "quantity": 8.0,
            }
        ]

        _apply_pending_sales(pending_sales, None)
        db.session.flush()

        assert list(location.products) == []
        sale = TerminalSale.query.filter_by(
            event_location_id=event_location.id, product_id=product.id
        ).one()
        assert sale.quantity == pytest.approx(8.0)


def test_location_total_summary_rows_override_amount(app):
    with app.app_context():
        event = Event(
            name="Summary Override Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Summary Stand")
        event_location = EventLocation(event=event, location=location)
        product = Product(name="Pretzel", price=7.5, cost=3.0)

        db.session.add_all([event, location, event_location, product])
        db.session.commit()

        net_total = 120.0
        discount_total = -10.0
        override_total = net_total + discount_total
        rows = [
            {
                "location": location.name,
                "product": product.name,
                "quantity": 15.0,
                "amount": 105.0,
            },
            {
                "location": location.name,
                "is_location_total": True,
                "quantity": 15.0,
                "amount": override_total,
                "net_including_tax_total": net_total,
                "discount_total": discount_total,
            },
        ]

        grouped = group_terminal_sales_rows(rows)
        location_summary = grouped[location.name]
        assert set(location_summary["products"].keys()) == {product.name}

        pending_sales = [
            {
                "event_location_id": event_location.id,
                "product_id": product.id,
                "product_name": product.name,
                "quantity": rows[0]["quantity"],
            }
        ]
        pending_totals = [
            {
                "event_location_id": event_location.id,
                "source_location": location.name,
                "total_quantity": location_summary.get("total"),
                "total_amount": location_summary.get("total_amount"),
                "net_including_tax_total": location_summary.get(
                    "net_including_tax_total"
                ),
                "discount_total": location_summary.get("discount_total"),
            }
        ]

        _apply_pending_sales(pending_sales, pending_totals)
        db.session.commit()

        summary = EventLocationTerminalSalesSummary.query.filter_by(
            event_location_id=event_location.id
        ).one()
        assert summary.total_amount == pytest.approx(override_total)
        assert summary.total_quantity == pytest.approx(location_summary.get("total"))


def test_apply_resolution_actions_adds_menu_entries(app):
    with app.app_context():
        event = Event(
            name="Menu Add Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Center Bar")
        event_location = EventLocation(event=event, location=location)
        product = Product(name="Craft Beer", price=9.5, cost=3.0)

        db.session.add_all([event, location, event_location, product])
        db.session.commit()

        queue = [
            {
                "event_location_id": event_location.id,
                "location_name": location.name,
                "sales_location": "CENTER BAR",
                "price_issues": [],
                "menu_issues": [
                    {
                        "product_id": product.id,
                        "product": product.name,
                        "menu_name": None,
                        "resolution": "add",
                    }
                ],
            }
        ]

        price_updates, menu_updates = _apply_resolution_actions({"queue": queue})
        db.session.flush()

        assert price_updates == []
        assert menu_updates == [f"{product.name} @ {location.name}"]
        assert product in location.products


def test_apply_resolution_actions_respects_skipped_menu_entries(app):
    with app.app_context():
        event = Event(
            name="Menu Skip Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Party Deck")
        event_location = EventLocation(event=event, location=location)
        product = Product(name="Party Platter", price=25.0, cost=10.0)

        db.session.add_all([event, location, event_location, product])
        db.session.commit()

        queue = [
            {
                "event_location_id": event_location.id,
                "location_name": location.name,
                "sales_location": "PARTY DECK",
                "price_issues": [],
                "menu_issues": [
                    {
                        "product_id": product.id,
                        "product": product.name,
                        "menu_name": None,
                        "resolution": "skip",
                    }
                ],
            }
        ]

        _apply_resolution_actions({"queue": queue})
        db.session.flush()

        assert product not in location.products


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


def test_parse_terminal_sales_number_strips_locale_prefixes():
    assert parse_terminal_sales_number("CA\u00A01,234.56") == pytest.approx(1234.56)
    assert parse_terminal_sales_number("C$\u00A0-98.76") == pytest.approx(-98.76)
    assert parse_terminal_sales_number("\u00A0ca$\u00A042") == pytest.approx(42.0)


def test_group_terminal_sales_rows_handles_locale_currency_totals():
    net_total = parse_terminal_sales_number("CA\u00A0123.46")
    discount_total = parse_terminal_sales_number("C$\u00A0-23.45")
    rows = [
        {
            "location": "Main Stand",
            "product": "Popcorn",
            "quantity": parse_terminal_sales_number("2"),
            "net_including_tax_total": net_total,
            "discount_total": discount_total,
        }
    ]

    grouped = group_terminal_sales_rows(rows)
    summary = grouped["Main Stand"]

    assert summary["net_including_tax_total"] == pytest.approx(net_total)
    assert summary["discount_total"] == pytest.approx(discount_total)
    assert summary["total_amount"] == pytest.approx(net_total + discount_total)


def test_derive_terminal_sales_quantity_uses_amount_when_quantity_missing():
    quantity = None
    derived = derive_terminal_sales_quantity(
        quantity,
        price=5.25,
        amount=5.25,
        net_including_tax_total=None,
        discounts_total=None,
    )
    assert derived == pytest.approx(1.0)


def test_derive_terminal_sales_quantity_handles_zero_quantity_with_net():
    quantity = 0.0
    derived = derive_terminal_sales_quantity(
        quantity,
        price=4.0,
        amount=None,
        net_including_tax_total=9.0,
        discounts_total=-1.0,
    )
    assert derived == pytest.approx(2.0)

def test_group_terminal_sales_rows_prefers_net_plus_discount_over_raw_amount():
    rows = [
        {
            "location": "Main Stand",
            "product": "Popcorn",
            "quantity": 5.0,
            "amount": 125.0,
            "net_including_tax_total": 100.0,
            "discount_total": 10.0,
        },
        {
            "location": "Main Stand",
            "product": "Soda",
            "quantity": 3.0,
            "amount": 45.0,
        },
    ]

    grouped = group_terminal_sales_rows(rows)
    summary = grouped["Main Stand"]

    # Even though raw totals are available, prefer the net total plus any discounts.
    assert summary["total_amount"] == pytest.approx(110.0)


def test_group_terminal_sales_rows_handles_comma_decimal_quantities():
    rows = [
        {
            "location": "Main Stand",
            "product": "Popcorn",
            "quantity": "1,0000",
        }
    ]

    grouped = group_terminal_sales_rows(rows)
    location_data = grouped["Main Stand"]
    product_data = location_data["products"]["Popcorn"]

    assert product_data["quantity"] == pytest.approx(1.0)
    assert location_data["total"] == pytest.approx(1.0)


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

        assert finish_response.status_code == 200
        finish_body = finish_response.data.decode()
        assert 'name="step" value="confirm_menus"' in finish_body, finish_body
        assert "Review Menu Additions" in finish_body

        menu_key = f"{event_location_id}:{product_id}"
        state_token_match = re.search(
            r'name="state_token" value="([^"]+)"', finish_body
        )
        assert state_token_match is not None
        state_token_value = state_token_match.group(1)

        with app.app_context():
            assert TerminalSale.query.count() == 0

        confirm_response = client.post(
            f"/events/{event_id}/terminal-sales",
            data={
                "step": "confirm_menus",
                "state_token": state_token_value,
                "menu_additions": menu_key,
                "action": "finish",
            },
            follow_redirects=False,
        )

        assert confirm_response.status_code == 302
        assert confirm_response.headers["Location"].endswith(f"/events/{event_id}")

    with app.app_context():
        sales = TerminalSale.query.filter_by(
            event_location_id=event_location_id
        ).all()
        assert len(sales) == 1
        assert sales[0].product_id == product_id
        location = EventLocation.query.get(event_location_id).location
        assert any(p.id == product_id for p in location.products)


def test_terminal_sales_upload_saves_locale_currency_totals(app, client):
    net_total = parse_terminal_sales_number("CA\u00A0123.46")
    discount_total = parse_terminal_sales_number("CA\u00A0-23.45")
    with app.app_context():
        event = Event(
            name="Locale Currency Event",
            start_date=date.today(),
            end_date=date.today(),
        )
        location = Location(name="Locale Stand")
        product = Product(name="Locale Popcorn", price=60.0, cost=20.0)
        location.products.append(product)
        event_location = EventLocation(event=event, location=location)
        db.session.add_all([event, location, product, event_location])
        db.session.commit()

        event_id = event.id
        event_location_id = event_location.id
        mapping_field = f"mapping-{event_location.id}"

    quantity_value = parse_terminal_sales_number("2")
    price_value = parse_terminal_sales_number("C$\u00A060.00")
    amount_value = parse_terminal_sales_number("CA\u00A0120.00")
    payload = json.dumps(
        {
            "rows": [
                {
                    "location": "Locale Stand",
                    "product": "Locale Popcorn",
                    "quantity": quantity_value,
                    "price": price_value,
                    "amount": amount_value,
                    "net_including_tax_total": net_total,
                    "discount_total": discount_total,
                }
            ],
            "filename": "terminal.xlsx",
        }
    )

    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    with client:
        login_response = login(client, admin_email, admin_pass)
        assert login_response.status_code == 200
        assert login_response.request.path != "/auth/login"

        finish_response = client.post(
            f"/events/{event_id}/terminal-sales",
            data={
                "step": "map",
                "payload": payload,
                "stage": "locations",
                mapping_field: "Locale Stand",
                "navigate": "finish",
            },
            follow_redirects=False,
        )

        assert finish_response.status_code == 302

        confirm_response = client.get(
            f"/events/{event_id}/locations/{event_location_id}/confirm",
            follow_redirects=False,
        )
        assert confirm_response.status_code == 200
        assert b"Terminal File Total" in confirm_response.data
        assert b"$100.01" in confirm_response.data

    with app.app_context():
        summary = db.session.get(
            EventLocationTerminalSalesSummary, event_location_id
        )
        assert summary is not None
        assert summary.total_quantity == pytest.approx(2.0)
        assert summary.total_amount == pytest.approx(net_total + discount_total)
        assert summary.source_location == "Locale Stand"

        sales = TerminalSale.query.filter_by(
            event_location_id=event_location_id
        ).all()
        assert len(sales) == 1
        assert sales[0].product.name == "Locale Popcorn"
        assert sales[0].quantity == pytest.approx(2.0)
