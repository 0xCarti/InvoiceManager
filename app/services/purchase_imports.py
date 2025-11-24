import csv
import datetime
from dataclasses import dataclass
from typing import IO, List, Optional

from werkzeug.datastructures import FileStorage

from app.models import Vendor
from app.utils.numeric import coerce_float


@dataclass
class ParsedPurchaseLine:
    description: str
    quantity: float
    unit_cost: Optional[float] = None


@dataclass
class ParsedPurchaseOrder:
    items: List[ParsedPurchaseLine]
    order_date: Optional[datetime.date] = None
    expected_date: Optional[datetime.date] = None


class CSVImportError(Exception):
    """Raised when a CSV import cannot be processed."""


_SYSCO_REQUIRED_HEADERS = {
    "item",
    "description",
    "qty ship",
    "price",
}


def _prepare_reader(file_obj: IO) -> csv.DictReader:
    file_obj.seek(0)
    return csv.DictReader(
        (line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else line
         for line in file_obj),
    )


def _normalize_headers(headers):
    return {header.strip().lower(): header for header in headers or []}


def _parse_sysco_csv(file_obj: IO) -> ParsedPurchaseOrder:
    reader = _prepare_reader(file_obj)
    header_map = _normalize_headers(reader.fieldnames)
    missing_headers = _SYSCO_REQUIRED_HEADERS - set(header_map)
    if missing_headers:
        readable = ", ".join(sorted(missing_headers))
        raise CSVImportError(
            f"Missing required Sysco columns: {readable}. Please upload the standard export file."
        )

    items: List[ParsedPurchaseLine] = []
    for row in reader:
        raw_description = row.get(header_map["description"], "").strip()
        raw_qty = row.get(header_map["qty ship"], "")
        raw_price = row.get(header_map["price"], "")

        quantity = coerce_float(raw_qty)
        if quantity is None or quantity <= 0:
            continue

        unit_cost = coerce_float(raw_price)
        items.append(
            ParsedPurchaseLine(
                description=raw_description or row.get(header_map["item"], "").strip(),
                quantity=quantity,
                unit_cost=unit_cost,
            )
        )

    if not items:
        raise CSVImportError("No purchasable lines found in the CSV file.")

    return ParsedPurchaseOrder(items=items)


def parse_purchase_order_csv(file: FileStorage, vendor: Vendor) -> ParsedPurchaseOrder:
    """Parse a vendor CSV into a purchase order structure."""

    if not file:
        raise CSVImportError("No file was provided for upload.")

    vendor_name = " ".join(filter(None, [vendor.first_name, vendor.last_name])).strip().lower()
    if "sysco" in vendor_name:
        return _parse_sysco_csv(file.stream)

    raise CSVImportError("CSV imports are not yet supported for this vendor.")
