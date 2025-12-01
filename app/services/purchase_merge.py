"""Helpers for merging purchase orders."""

from __future__ import annotations

import json
from typing import Dict, List, Sequence

from sqlalchemy.orm import selectinload

from app import db
from app.models import PurchaseInvoiceDraft, PurchaseOrder
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

    next_position = (
        max((item.position for item in target_order.items), default=-1) + 1
    )

    draft_position_map: Dict[tuple[int, int], int] = {}

    for source in source_orders:
        for item in sorted(source.items, key=lambda itm: itm.position):
            draft_position_map[(source.id, item.position)] = next_position
            source.items.remove(item)
            target_order.items.append(item)
            item.purchase_order_id = target_order.id
            item.position = next_position
            next_position += 1

    total_delivery = (target_order.delivery_charge or 0.0) + sum(
        source.delivery_charge or 0.0 for source in source_orders
    )
    target_order.delivery_charge = total_delivery

    _merge_invoice_drafts(
        target_order,
        source_orders,
        draft_position_map,
    )

    for source in source_orders:
        db.session.delete(source)

    db.session.commit()

    merged_ids = ", ".join(map(str, source_po_ids))
    log_activity(f"Merged purchase orders {merged_ids} into {target_order.id}")

    return target_order


def _merge_invoice_drafts(
    target_order: PurchaseOrder,
    source_orders: List[PurchaseOrder],
    draft_position_map: Dict[tuple[int, int], int],
) -> None:
    """Merge or migrate invoice drafts for the merged purchase orders."""

    target_draft = PurchaseInvoiceDraft.query.filter_by(
        purchase_order_id=target_order.id
    ).first()
    source_drafts = {
        draft.purchase_order_id: draft
        for draft in PurchaseInvoiceDraft.query.filter(
            PurchaseInvoiceDraft.purchase_order_id.in_(
                [order.id for order in source_orders]
            )
        )
    }

    if not target_draft and not source_drafts:
        return

    base_payload = target_draft.data if target_draft else {}
    base_items = list(base_payload.get("items", []) or [])

    draft_sources = []

    for source in source_orders:
        draft = source_drafts.get(source.id)
        if not draft:
            continue
        draft_sources.append(source.id)
        incoming = draft.data or {}
        updated_items = []
        for item in incoming.get("items", []) or []:
            mapped_position = draft_position_map.get(
                (source.id, item.get("position"))
            )
            item_copy = dict(item)
            if mapped_position is not None:
                item_copy["position"] = mapped_position
            updated_items.append(item_copy)

        for key in [
            "invoice_number",
            "received_date",
            "location_id",
            "department",
            "gst",
            "pst",
            "delivery_charge",
        ]:
            incoming_value = incoming.get(key)
            base_value = base_payload.get(key)
            if base_value in (None, "") and incoming_value not in (None, ""):
                base_payload[key] = incoming_value
            elif (
                base_value not in (None, "")
                and incoming_value not in (None, "")
                and incoming_value != base_value
            ):
                raise PurchaseMergeError(
                    "Purchase invoice drafts contain conflicting values and cannot be merged."
                )

        base_items.extend(updated_items)

    positions_in_payload = {
        item.get("position") for item in base_items if item.get("position") is not None
    }
    for item in sorted(target_order.items, key=lambda itm: itm.position):
        if item.position in positions_in_payload:
            continue
        base_items.append(
            {
                "item_id": item.item_id,
                "unit_id": item.unit_id,
                "quantity": item.quantity,
                "cost": item.unit_cost,
                "position": item.position,
                "gl_code_id": None,
                "location_id": None,
            }
        )

    base_items.sort(key=lambda itm: (itm.get("position") is None, itm.get("position", 0)))
    base_payload["items"] = base_items

    if target_draft:
        target_draft.update_payload(base_payload)
    else:
        target_draft = PurchaseInvoiceDraft(
            purchase_order_id=target_order.id, payload=json.dumps(base_payload)
        )
        db.session.add(target_draft)

    if source_drafts:
        for draft in source_drafts.values():
            db.session.delete(draft)

    if draft_sources:
        merged_ids = ", ".join(map(str, draft_sources))
        log_activity(
            f"Merged purchase invoice drafts from purchase orders {merged_ids} into {target_order.id}"
        )

