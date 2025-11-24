import csv
import datetime
from dataclasses import dataclass
from typing import IO, List, Optional

from werkzeug.datastructures import FileStorage

from app.models import Item, Vendor, VendorItemAlias
from app.utils.pos_import import normalize_pos_alias
from app.utils.numeric import coerce_float


@dataclass
class ParsedPurchaseLine:
    vendor_sku: Optional[str]
    vendor_description: str
    pack_size: Optional[str]
    quantity: float
    unit_cost: Optional[float] = None


@dataclass
class ResolvedPurchaseLine:
    parsed_line: ParsedPurchaseLine
    alias: Optional[VendorItemAlias]
    item_id: Optional[int] = None
    unit_id: Optional[int] = None
    cost: Optional[float] = None


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
        vendor_sku = row.get(header_map["item"], "").strip()

        quantity = coerce_float(raw_qty)
        if quantity is None or quantity <= 0:
            continue

        unit_cost = coerce_float(raw_price)
        items.append(
            ParsedPurchaseLine(
                vendor_sku=vendor_sku or None,
                vendor_description=raw_description or vendor_sku,
                pack_size=None,
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


def _default_unit_for_item(item: Item, preferred_unit_id: int | None = None) -> int | None:
    if preferred_unit_id:
        for unit in item.units:
            if unit.id == preferred_unit_id:
                return preferred_unit_id
    for unit in item.units:
        if unit.receiving_default:
            return unit.id
    return item.units[0].id if item.units else None


def normalize_vendor_alias_text(value: str | None) -> str:
    return normalize_pos_alias(value or "")


def update_or_create_vendor_alias(
    *,
    vendor: Vendor,
    item_id: int,
    item_unit_id: int | None,
    vendor_sku: str | None,
    vendor_description: str | None,
    pack_size: str | None,
    default_cost: float | None,
) -> VendorItemAlias:
    normalized_description = normalize_vendor_alias_text(vendor_description or vendor_sku)

    alias = None
    if vendor_sku:
        alias = VendorItemAlias.query.filter_by(
            vendor_id=vendor.id, vendor_sku=vendor_sku
        ).first()
    if alias is None and normalized_description:
        alias = VendorItemAlias.query.filter_by(
            vendor_id=vendor.id, normalized_description=normalized_description
        ).first()
    if alias is None:
        alias = VendorItemAlias(vendor_id=vendor.id)

    alias.vendor_sku = vendor_sku or None
    alias.vendor_description = vendor_description or vendor_sku
    alias.normalized_description = normalized_description or None
    alias.pack_size = pack_size or None
    alias.item_id = item_id
    alias.item_unit_id = item_unit_id
    alias.default_cost = default_cost

    return alias


def resolve_vendor_purchase_lines(
    vendor: Vendor, parsed_lines: List[ParsedPurchaseLine]
) -> List[ResolvedPurchaseLine]:
    if not parsed_lines:
        return []

    vendor_aliases = VendorItemAlias.query.filter_by(vendor_id=vendor.id).all()
    alias_by_sku = {alias.vendor_sku: alias for alias in vendor_aliases if alias.vendor_sku}
    alias_by_description = {
        alias.normalized_description: alias
        for alias in vendor_aliases
        if alias.normalized_description
    }

    resolved: List[ResolvedPurchaseLine] = []
    for parsed_line in parsed_lines:
        normalized_description = normalize_vendor_alias_text(
            parsed_line.vendor_description
        )
        alias = None
        if parsed_line.vendor_sku:
            alias = alias_by_sku.get(parsed_line.vendor_sku)
        if alias is None and normalized_description:
            alias = alias_by_description.get(normalized_description)

        item_id = None
        unit_id = None
        resolved_cost = parsed_line.unit_cost

        if alias and alias.item:
            item_id = alias.item_id
            unit_id = _default_unit_for_item(alias.item, alias.item_unit_id)
            if resolved_cost is None:
                resolved_cost = alias.default_cost

        resolved.append(
            ResolvedPurchaseLine(
                parsed_line=parsed_line,
                alias=alias,
                item_id=item_id,
                unit_id=unit_id,
                cost=resolved_cost,
            )
        )

    return resolved


def serialize_parsed_line(line: ParsedPurchaseLine) -> dict:
    return {
        "vendor_sku": line.vendor_sku,
        "vendor_description": line.vendor_description,
        "pack_size": line.pack_size,
        "quantity": line.quantity,
        "unit_cost": line.unit_cost,
    }
