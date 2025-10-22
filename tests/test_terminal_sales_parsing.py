from app.utils.pos_import import extract_terminal_sales_location


def test_extract_location_all_blank_cells():
    row = ["PRIVATE SUITES", "", "", None, "  ", 0, 0.0]
    assert extract_terminal_sales_location(row) == "PRIVATE SUITES"


def test_extract_location_handles_whitespace_only_cells():
    row = ["Keystone Kravings", "   ", None, "\t", "", 0.0]
    assert extract_terminal_sales_location(row) == "Keystone Kravings"


def test_extract_location_treats_numeric_rows_as_data():
    row = ["799", "17oz Draft Beer - Pilsner BWK", 9.44, 1.01, 17.0]
    assert extract_terminal_sales_location(row) is None


def test_extract_location_requires_text_header():
    row = [None, "", ""]
    assert extract_terminal_sales_location(row) is None
