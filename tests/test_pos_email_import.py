from decimal import Decimal

from app.utils.pos_import import parse_terminal_sales_email_rows


def test_parse_terminal_sales_email_rows_detects_locations_and_totals():
    rows = [
        ["PRIVATE SUITES", "", "", None, "", "", "", "", ""],
        [" Product Code ", "Product Name", "", "", "QTY", "", "", "Net Inc", "Discounts"],
        [799, "17oz Draft Beer", "", "", "2", "", "", '"1,234.50"', "-23.45"],
        ["", "", "", "", "3", "", "", "100.00", "-5.00"],
        ["TAP ROOM", "", "", "", "", "", "", "", ""],
        ["1001", "Comp Item", "", "", "0", "", "", "12.00", "-2.00"],
    ]

    parsed = parse_terminal_sales_email_rows(rows)

    assert list(parsed.keys()) == ["PRIVATE SUITES", "TAP ROOM"]

    suites_rows = parsed["PRIVATE SUITES"]["rows"]
    assert len(suites_rows) == 1
    assert suites_rows[0]["source_product_code"] == "799"
    assert suites_rows[0]["source_product_name"] == "17oz Draft Beer"
    assert suites_rows[0]["quantity"] == Decimal("2")
    assert suites_rows[0]["net_inc"] == Decimal("1234.50")
    assert suites_rows[0]["discount_raw"] == Decimal("-23.45")
    assert suites_rows[0]["discount_abs"] == Decimal("23.45")
    assert suites_rows[0]["line_total"] == Decimal("1257.95")
    assert suites_rows[0]["unit_price"] == Decimal("628.975")
    assert suites_rows[0]["raw_row"][1] == "17oz Draft Beer"

    suites_totals = parsed["PRIVATE SUITES"]["location_totals"]
    assert len(suites_totals) == 1
    assert suites_totals[0]["quantity"] == Decimal("3")
    assert suites_totals[0]["line_total"] == Decimal("105.00")

    tap_rows = parsed["TAP ROOM"]["rows"]
    assert len(tap_rows) == 1
    assert tap_rows[0]["quantity"] == Decimal("0")
    assert tap_rows[0]["line_total"] == Decimal("14.00")
    assert tap_rows[0]["unit_price"] == Decimal("14.00")
