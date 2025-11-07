import math

import pytest

from app.utils.pos_import import (
    combine_terminal_sales_totals,
    group_terminal_sales_rows,
)


def test_terminal_sales_combined_totals_drive_unit_price():
    location_name = "Main Stand"
    product_name = "Discounted Pretzel"
    quantity = 2.0
    net_total = 90.0
    discount_total = -10.0

    rows = [
        {
            "location": location_name,
            "product": product_name,
            "quantity": quantity,
            # Spreadsheet price column provided a value that does not include discounts.
            "price": 55.0,
            "amount": 110.0,
            "net_including_tax_total": net_total,
            "discount_total": discount_total,
        }
    ]

    grouped = group_terminal_sales_rows(rows)
    product_summary = grouped[location_name]["products"][product_name]

    assert product_summary.get("net_including_tax_total") == pytest.approx(net_total)
    assert product_summary.get("discount_total") == pytest.approx(discount_total)
    assert product_summary["quantity"] == pytest.approx(quantity)

    combined_total = combine_terminal_sales_totals(
        product_summary.get("net_including_tax_total"),
        product_summary.get("discount_total"),
    )
    assert combined_total == pytest.approx(net_total + discount_total)

    derived_unit_price = combined_total / product_summary["quantity"]
    assert derived_unit_price == pytest.approx(
        (net_total + discount_total) / product_summary["quantity"]
    )

    file_prices = [price for price in product_summary["prices"] if price is not None]
    assert file_prices == pytest.approx([55.0])

    price_candidates = [derived_unit_price]
    price_candidates.extend(file_prices)
    terminal_price_value = derived_unit_price

    assert price_candidates[0] == pytest.approx(derived_unit_price)
    assert terminal_price_value == pytest.approx(derived_unit_price)

    catalog_price = 55.0
    assert not all(
        math.isclose(price, catalog_price, abs_tol=0.01) for price in price_candidates
    )
