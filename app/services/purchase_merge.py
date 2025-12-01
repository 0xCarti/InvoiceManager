"""Helpers for merging purchase orders."""

from __future__ import annotations

from typing import List, Sequence

from sqlalchemy.orm import selectinload

from app import db
from app.models import PurchaseOrder
from app.utils.activity import log_activity


class PurchaseMergeError(Exception):
    """Raised when a merge request cannot be completed."""


def merge_purchase_orders(
    target_po_id: int,
    source_po_ids: Sequence[int],
    *,
    require_expected_date_match: bool = True,
) -> PurchaseOrder:
    """Merge purchase orders into a single target order.

    Args:
        target_po_id: The ID of the purchase order to merge into.
        source_po_ids: A list of purchase order IDs to be merged into the target.
        require_expected_date_match: When True, all orders must share the same
            expected date.

    Returns:
        The updated target :class:`PurchaseOrder` instance.

    Raises:
        PurchaseMergeError: If validation fails or any order is missing.
    """

    if not source_po_ids:
        raise PurchaseMergeError("At least one source purchase order must be provided.")

    if target_po_id in source_po_ids:
        raise PurchaseMergeError("Target purchase order cannot be one of the sources.")

    all_ids = set(source_po_ids) | {target_po_id}
    orders: List[PurchaseOrder] = (
        PurchaseOrder.query.options(selectinload(PurchaseOrder.items))
        .filter(PurchaseOrder.id.in_(all_ids))
        .all()
    )

    if len(orders) != len(all_ids):
        missing = sorted(all_ids - {order.id for order in orders})
        raise PurchaseMergeError(
            f"Purchase order(s) not found: {', '.join(map(str, missing))}"
        )

    order_lookup = {order.id: order for order in orders}
    target_order = order_lookup[target_po_id]
    source_orders = [order_lookup[po_id] for po_id in source_po_ids]

    if target_order.received:
        raise PurchaseMergeError("Cannot merge into an order that has already been received.")

    vendor_id = target_order.vendor_id
    for source in source_orders:
        if source.received:
            raise PurchaseMergeError("All source purchase orders must be unreceived.")
        if source.vendor_id != vendor_id:
            raise PurchaseMergeError("All purchase orders must share the same vendor.")
        if require_expected_date_match and source.expected_date != target_order.expected_date:
            raise PurchaseMergeError("All purchase orders must share the same expected date.")

    with db.session.begin():
        next_position = (
            max((item.position for item in target_order.items), default=-1) + 1
        )

        for source in source_orders:
            for item in sorted(source.items, key=lambda itm: itm.position):
                item.purchase_order_id = target_order.id
                item.position = next_position
                next_position += 1

        total_delivery = (target_order.delivery_charge or 0.0) + sum(
            source.delivery_charge or 0.0 for source in source_orders
        )
        target_order.delivery_charge = total_delivery

        for source in source_orders:
            db.session.delete(source)

    merged_ids = ", ".join(map(str, source_po_ids))
    log_activity(f"Merged purchase orders {merged_ids} into {target_order.id}")

    return target_order

