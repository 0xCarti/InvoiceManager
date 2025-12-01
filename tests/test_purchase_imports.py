import io

import pytest
from werkzeug.datastructures import FileStorage

from app.models import Vendor
from app.services.purchase_imports import (
    CSVImportError,
    ParsedPurchaseLine,
    parse_purchase_order_csv,
)


def _make_pratts_file(csv_text: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(csv_text.encode()), filename="pratts.csv")


def _make_pratts_vendor() -> Vendor:
    return Vendor(first_name="Pratt", last_name="Supplies")


def test_parse_pratts_csv_success():
    csv_text = """Item,Pack,Size,Brand,Description,Quantity Shipped,Unit Price,Extended Price,PO Number
1001,1,12 oz,BrandA,First Item,4,2.50,10.00,PO-123
1002,2,6 ct,BrandB,,3,1.00,3.00,PO-123
"""
    parsed = parse_purchase_order_csv(_make_pratts_file(csv_text), _make_pratts_vendor())

    assert len(parsed.items) == 2
    assert parsed.order_number == "PO-123"
    assert parsed.expected_total == 13

    first: ParsedPurchaseLine = parsed.items[0]
    assert first.vendor_sku == "1001"
    assert first.vendor_description == "First Item"
    assert first.pack_size == "1 12 oz"
    assert first.quantity == 4
    assert first.unit_cost == 2.5

    second: ParsedPurchaseLine = parsed.items[1]
    assert second.vendor_sku == "1002"
    assert second.vendor_description == "1002"
    assert second.pack_size == "2 6 ct"
    assert second.quantity == 3
    assert second.unit_cost == 1


def test_parse_pratts_csv_missing_headers():
    csv_text = """Item,Size,Brand,Description,Qty Ship,Price,Ext Price
1001,1,BrandA,First Item,4,2.50,10.00
"""

    with pytest.raises(CSVImportError) as excinfo:
        parse_purchase_order_csv(_make_pratts_file(csv_text), _make_pratts_vendor())

    assert "Missing required Pratts columns" in str(excinfo.value)
    assert "pack" in str(excinfo.value)


def test_parse_pratts_csv_invalid_quantities():
    csv_text = """Item,Pack,Size,Brand,Description,Qty Ship,Price,Ext Price
1001,1,12 oz,BrandA,First Item,0,2.50,0.00
1002,2,6 ct,BrandB,Second Item,,1.00,0.00
1003,3,5 lb,BrandC,Third Item,-1,3.00,-3.00
"""

    with pytest.raises(CSVImportError) as excinfo:
        parse_purchase_order_csv(_make_pratts_file(csv_text), _make_pratts_vendor())

    assert "No purchasable lines found" in str(excinfo.value)
