from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app import db
from app.forms import (
    ConfirmForm,
    DeleteForm,
    PurchaseOrderForm,
    ReceiveInvoiceForm,
)
from app.models import (
    GLCode,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemArchive,
    Vendor,
)
from app.utils.activity import log_activity
from app.utils.pagination import build_pagination_args, get_per_page

import datetime

from sqlalchemy.orm import selectinload

purchase = Blueprint("purchase", __name__)


def check_negative_invoice_reverse(invoice_obj):
    """Return warnings if reversing the invoice would cause negative inventory."""
    warnings = []
    for inv_item in invoice_obj.items:
        factor = 1
        if inv_item.unit_id:
            unit = db.session.get(ItemUnit, inv_item.unit_id)
            if unit:
                factor = unit.factor
        itm = db.session.get(Item, inv_item.item_id)
        if itm:
            record = LocationStandItem.query.filter_by(
                location_id=invoice_obj.location_id,
                item_id=itm.id,
            ).first()
            current = record.expected_count if record else 0
            new_count = current - inv_item.quantity * factor
            if new_count < 0:
                loc = (
                    record.location
                    if record
                    else db.session.get(Location, invoice_obj.location_id)
                )
                location_name = loc.name if loc else invoice_obj.location_name
                warnings.append(
                    f"Reversing this invoice will result in negative inventory for {itm.name} at {location_name}"
                )
        else:
            warnings.append(
                f"Cannot reverse invoice because item '{inv_item.item_name}' no longer exists"
            )
    return warnings


@purchase.route("/purchase_orders", methods=["GET"])
@login_required
def view_purchase_orders():
    """Show purchase orders with optional filters."""
    delete_form = DeleteForm()
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    vendor_id = request.args.get("vendor_id", type=int)
    status = request.args.get("status", "pending")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    start_date = (
        datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        if start_date_str
        else None
    )
    end_date = (
        datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
        if end_date_str
        else None
    )

    query = PurchaseOrder.query

    if status == "pending":
        query = query.filter_by(received=False)
    elif status == "completed":
        query = query.filter_by(received=True)

    if vendor_id:
        query = query.filter(PurchaseOrder.vendor_id == vendor_id)
    if start_date:
        query = query.filter(PurchaseOrder.order_date >= start_date)
    if end_date:
        query = query.filter(PurchaseOrder.order_date <= end_date)

    query = query.options(
        selectinload(PurchaseOrder.vendor),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.product),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
    )

    orders = query.order_by(PurchaseOrder.order_date.desc()).paginate(
        page=page, per_page=per_page
    )

    vendors = Vendor.query.filter_by(archived=False).all()
    selected_vendor = db.session.get(Vendor, vendor_id) if vendor_id else None
    return render_template(
        "purchase_orders/view_purchase_orders.html",
        orders=orders,
        delete_form=delete_form,
        vendors=vendors,
        vendor_id=vendor_id,
        start_date=start_date_str,
        end_date=end_date_str,
        status=status,
        selected_vendor=selected_vendor,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
    )


@purchase.route("/purchase_orders/create", methods=["GET", "POST"])
@login_required
def create_purchase_order():
    """Create a purchase order."""
    form = PurchaseOrderForm()
    if form.validate_on_submit():
        po = PurchaseOrder(
            vendor_id=form.vendor.data,
            user_id=current_user.id,
            vendor_name=f"{db.session.get(Vendor, form.vendor.data).first_name} {db.session.get(Vendor, form.vendor.data).last_name}",
            order_date=form.order_date.data,
            expected_date=form.expected_date.data,
            delivery_charge=form.delivery_charge.data or 0.0,
        )
        db.session.add(po)
        db.session.commit()

        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = request.form.get(f"items-{index}-quantity", type=float)
            if item_id and quantity is not None:
                db.session.add(
                    PurchaseOrderItem(
                        purchase_order_id=po.id,
                        item_id=item_id,
                        unit_id=unit_id,
                        quantity=quantity,
                    )
                )

        db.session.commit()
        log_activity(f"Created purchase order {po.id}")
        flash("Purchase order created successfully!", "success")
        return redirect(url_for("purchase.view_purchase_orders"))

    selected_item_ids = []
    for item_form in form.items:
        if item_form.item.data:
            try:
                selected_item_ids.append(int(item_form.item.data))
            except (TypeError, ValueError):
                continue
    item_lookup = {}
    if selected_item_ids:
        item_lookup = {
            item.id: item.name
            for item in Item.query.filter(Item.id.in_(selected_item_ids)).all()
        }

    codes = GLCode.query.filter(GLCode.code.like("5%"))
    return render_template(
        "purchase_orders/create_purchase_order.html",
        form=form,
        gl_codes=codes,
        item_lookup=item_lookup,
    )


@purchase.route("/purchase_orders/edit/<int:po_id>", methods=["GET", "POST"])
@login_required
def edit_purchase_order(po_id):
    """Modify a pending purchase order."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    form = PurchaseOrderForm()
    if form.validate_on_submit():
        po.vendor_id = form.vendor.data
        po.vendor_name = f"{db.session.get(Vendor, form.vendor.data).first_name} {db.session.get(Vendor, form.vendor.data).last_name}"
        po.order_date = form.order_date.data
        po.expected_date = form.expected_date.data
        po.delivery_charge = form.delivery_charge.data or 0.0

        PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).delete()

        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = request.form.get(f"items-{index}-quantity", type=float)
            if item_id and quantity is not None:
                db.session.add(
                    PurchaseOrderItem(
                        purchase_order_id=po.id,
                        item_id=item_id,
                        unit_id=unit_id,
                        quantity=quantity,
                    )
                )

        db.session.commit()
        log_activity(f"Edited purchase order {po.id}")
        flash("Purchase order updated successfully!", "success")
        return redirect(url_for("purchase.view_purchase_orders"))

    if request.method == "GET":
        form.vendor.data = po.vendor_id
        form.order_date.data = po.order_date
        form.expected_date.data = po.expected_date
        form.delivery_charge.data = po.delivery_charge
        form.items.min_entries = max(1, len(po.items))
        for i, poi in enumerate(po.items):
            if len(form.items) <= i:
                form.items.append_entry()
        for i, poi in enumerate(po.items):
            form.items[i].item.data = poi.item_id
            form.items[i].unit.data = poi.unit_id
            form.items[i].quantity.data = poi.quantity

    selected_item_ids = []
    for item_form in form.items:
        if item_form.item.data:
            try:
                selected_item_ids.append(int(item_form.item.data))
            except (TypeError, ValueError):
                continue
    item_lookup = {}
    if selected_item_ids:
        item_lookup = {
            item.id: item.name
            for item in Item.query.filter(Item.id.in_(selected_item_ids)).all()
        }

    codes = GLCode.query.filter(GLCode.code.like("5%"))
    return render_template(
        "purchase_orders/edit_purchase_order.html",
        form=form,
        po=po,
        gl_codes=codes,
        item_lookup=item_lookup,
    )


@purchase.route("/purchase_orders/<int:po_id>/delete", methods=["POST"])
@login_required
def delete_purchase_order(po_id):
    """Delete an unreceived purchase order."""
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    if po.received:
        flash(
            "Cannot delete a purchase order that has been received.", "error"
        )
        return redirect(url_for("purchase.view_purchase_orders"))
    db.session.delete(po)
    db.session.commit()
    log_activity(f"Deleted purchase order {po.id}")
    flash("Purchase order deleted successfully!", "success")
    return redirect(url_for("purchase.view_purchase_orders"))


@purchase.route(
    "/purchase_orders/<int:po_id>/receive", methods=["GET", "POST"]
)
@login_required
def receive_invoice(po_id):
    """Receive a purchase order and create an invoice."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    form = ReceiveInvoiceForm()
    if request.method == "GET":
        form.delivery_charge.data = po.delivery_charge
        form.items.min_entries = max(1, len(po.items))
        while len(form.items) < len(po.items):
            form.items.append_entry()
        for item_form in form.items:
            item_form.item.choices = [
                (i.id, i.name)
                for i in Item.query.filter_by(archived=False).all()
            ]
            item_form.unit.choices = [
                (u.id, u.name) for u in ItemUnit.query.all()
            ]
        for i, poi in enumerate(po.items):
            form.items[i].item.data = poi.item_id
            form.items[i].unit.data = poi.unit_id
            form.items[i].quantity.data = poi.quantity
    if form.validate_on_submit():
        if not PurchaseOrderItemArchive.query.filter_by(
            purchase_order_id=po.id
        ).first():
            for poi in po.items:
                db.session.add(
                    PurchaseOrderItemArchive(
                        purchase_order_id=po.id,
                        item_id=poi.item_id,
                        unit_id=poi.unit_id,
                        quantity=poi.quantity,
                    )
                )
            db.session.commit()
        invoice = PurchaseInvoice(
            purchase_order_id=po.id,
            user_id=current_user.id,
            location_id=form.location_id.data,
            vendor_name=po.vendor_name,
            location_name=db.session.get(Location, form.location_id.data).name,
            received_date=form.received_date.data,
            invoice_number=form.invoice_number.data,
            gst=form.gst.data or 0.0,
            pst=form.pst.data or 0.0,
            delivery_charge=form.delivery_charge.data or 0.0,
        )
        db.session.add(invoice)
        # Flush so the invoice has an ID for related line items without
        # committing the transaction yet. This keeps all updates in a single
        # commit so item cost changes persist reliably.
        db.session.flush()

        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = request.form.get(f"items-{index}-quantity", type=float)
            cost = request.form.get(f"items-{index}-cost", type=float)
            if item_id and quantity is not None and cost is not None:
                cost = abs(cost)

                item_obj = db.session.get(Item, item_id)
                unit_obj = (
                    db.session.get(ItemUnit, unit_id) if unit_id else None
                )

                prev_cost = item_obj.cost if item_obj and item_obj.cost else 0.0
                db.session.add(
                    PurchaseInvoiceItem(
                        invoice_id=invoice.id,
                        item_id=item_obj.id if item_obj else None,
                        unit_id=unit_obj.id if unit_obj else None,
                        item_name=item_obj.name if item_obj else "",
                        unit_name=unit_obj.name if unit_obj else None,
                        quantity=quantity,
                        cost=cost,
                        prev_cost=prev_cost,
                    )
                )

                if item_obj:
                    factor = unit_obj.factor if unit_obj and unit_obj.factor else 1
                    prev_qty = (
                        db.session.query(
                            db.func.sum(LocationStandItem.expected_count)
                        )
                        .filter(LocationStandItem.item_id == item_obj.id)
                        .scalar()
                        or 0
                    )
                    new_qty = quantity * factor
                    total_qty = prev_qty + new_qty

                    # Cost per base unit for the newly received stock
                    cost_per_unit = cost / factor if factor else cost
                    prev_total_cost = prev_qty * prev_cost
                    new_total_cost = cost_per_unit * new_qty
                    if total_qty > 0:
                        weighted_cost = (prev_total_cost + new_total_cost) / total_qty
                    else:
                        weighted_cost = cost_per_unit

                    item_obj.quantity = total_qty
                    item_obj.cost = weighted_cost

                    # Explicitly mark the item as dirty so cost updates persist
                    db.session.add(item_obj)

                    record = LocationStandItem.query.filter_by(
                        location_id=invoice.location_id, item_id=item_obj.id
                    ).first()
                    if not record:
                        record = LocationStandItem(
                            location_id=invoice.location_id,
                            item_id=item_obj.id,
                            expected_count=0,
                            purchase_gl_code_id=item_obj.purchase_gl_code_id,
                        )
                        db.session.add(record)
                    elif (
                        record.purchase_gl_code_id is None
                        and item_obj.purchase_gl_code_id is not None
                    ):
                        record.purchase_gl_code_id = (
                            item_obj.purchase_gl_code_id
                        )
                    record.expected_count += quantity * factor

                    # Ensure the in-memory changes are sent to the database so
                    # subsequent iterations or queries within this request see
                    # the updated cost and quantity values immediately.
                    db.session.flush()
        po.received = True
        db.session.add(po)
        # Commit once so that invoice, items, and updated item costs are saved
        # atomically, ensuring the weighted cost persists in the database.
        db.session.commit()
        log_activity(f"Received invoice {invoice.id} for PO {po.id}")
        flash("Invoice received successfully!", "success")
        return redirect(url_for("purchase.view_purchase_invoices"))

    return render_template(
        "purchase_orders/receive_invoice.html", form=form, po=po
    )


@purchase.route("/purchase_invoices", methods=["GET"])
@login_required
def view_purchase_invoices():
    """List all received purchase invoices."""
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    invoice_id = request.args.get("invoice_id", type=int)
    po_number = request.args.get("po_number", type=int)
    vendor_id = request.args.get("vendor_id", type=int)
    location_id = request.args.get("location_id", type=int)
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.date.fromisoformat(start_date_str)
        except ValueError:
            flash("Invalid start date.", "error")
            return redirect(url_for("purchase.view_purchase_invoices"))
    if end_date_str:
        try:
            end_date = datetime.date.fromisoformat(end_date_str)
        except ValueError:
            flash("Invalid end date.", "error")
            return redirect(url_for("purchase.view_purchase_invoices"))
    if start_date and end_date and start_date > end_date:
        flash("Invalid date range: start cannot be after end.", "error")
        return redirect(url_for("purchase.view_purchase_invoices"))

    query = PurchaseInvoice.query.options(
        selectinload(PurchaseInvoice.purchase_order).selectinload(PurchaseOrder.vendor),
        selectinload(PurchaseInvoice.items),
    )
    if invoice_id:
        query = query.filter(PurchaseInvoice.id == invoice_id)
    if po_number:
        query = query.filter(PurchaseInvoice.purchase_order_id == po_number)
    if vendor_id:
        query = query.join(PurchaseOrder).filter(PurchaseOrder.vendor_id == vendor_id)
    if location_id:
        query = query.filter(PurchaseInvoice.location_id == location_id)
    if start_date:
        query = query.filter(PurchaseInvoice.received_date >= start_date)
    if end_date:
        query = query.filter(PurchaseInvoice.received_date <= end_date)

    invoices = query.order_by(
        PurchaseInvoice.received_date.desc(), PurchaseInvoice.id.desc()
    ).paginate(page=page, per_page=per_page)

    vendors = Vendor.query.order_by(Vendor.first_name, Vendor.last_name).all()
    locations = Location.query.order_by(Location.name).all()
    active_vendor = db.session.get(Vendor, vendor_id) if vendor_id else None
    active_location = db.session.get(Location, location_id) if location_id else None

    return render_template(
        "purchase_invoices/view_purchase_invoices.html",
        invoices=invoices,
        vendors=vendors,
        locations=locations,
        invoice_id=invoice_id,
        po_number=po_number,
        vendor_id=vendor_id,
        location_id=location_id,
        start_date=start_date_str,
        end_date=end_date_str,
        active_vendor=active_vendor,
        active_location=active_location,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
    )


@purchase.route("/purchase_invoices/<int:invoice_id>")
@login_required
def view_purchase_invoice(invoice_id):
    """Display a purchase invoice."""
    invoice = db.session.get(PurchaseInvoice, invoice_id)
    if invoice is None:
        abort(404)
    return render_template(
        "purchase_invoices/view_purchase_invoice.html", invoice=invoice
    )


@purchase.route("/purchase_invoices/<int:invoice_id>/report")
@login_required
def purchase_invoice_report(invoice_id):
    """Generate a GL code summary for a purchase invoice."""
    invoice = db.session.get(PurchaseInvoice, invoice_id)
    if invoice is None:
        abort(404)

    gl_totals = {}
    item_total = 0
    for it in invoice.items:
        line_total = it.line_total
        item_total += line_total
        code = None
        if it.item:
            gl = it.item.purchase_gl_code_for_location(invoice.location_id)
            code = gl.code if gl else None
        if not code:
            code = "Unassigned"
        gl_totals[code] = gl_totals.get(code, 0) + line_total

    if item_total:
        for code, value in list(gl_totals.items()):
            share = value / item_total
            gl_totals[code] = (
                value + share * invoice.pst + share * invoice.delivery_charge
            )

    if invoice.gst:
        gl_totals["102702"] = gl_totals.get("102702", 0) + invoice.gst

    report = sorted(gl_totals.items())
    return render_template(
        "purchase_invoices/invoice_gl_report.html",
        invoice=invoice,
        report=report,
    )


@purchase.route(
    "/purchase_invoices/<int:invoice_id>/reverse", methods=["GET", "POST"]
)
@login_required
def reverse_purchase_invoice(invoice_id):
    """Undo receipt of a purchase invoice."""
    invoice = db.session.get(PurchaseInvoice, invoice_id)
    if invoice is None:
        abort(404)
    po = db.session.get(PurchaseOrder, invoice.purchase_order_id)
    if po is None:
        abort(404)
    warnings = check_negative_invoice_reverse(invoice)
    form = ConfirmForm()
    if warnings and request.method == "GET":
        return render_template(
            "confirm_action.html",
            form=form,
            warnings=warnings,
            action_url=url_for(
                "purchase.reverse_purchase_invoice", invoice_id=invoice_id
            ),
            cancel_url=url_for("purchase.view_purchase_invoices"),
            title="Confirm Invoice Reversal",
        )
    if warnings and not form.validate_on_submit():
        return render_template(
            "confirm_action.html",
            form=form,
            warnings=warnings,
            action_url=url_for(
                "purchase.reverse_purchase_invoice", invoice_id=invoice_id
            ),
            cancel_url=url_for("purchase.view_purchase_invoices"),
            title="Confirm Invoice Reversal",
        )
    for inv_item in invoice.items:
        factor = 1
        if inv_item.unit_id:
            unit = db.session.get(ItemUnit, inv_item.unit_id)
            if unit:
                factor = unit.factor
        itm = db.session.get(Item, inv_item.item_id)
        if not itm:
            flash(
                f"Cannot reverse invoice because item '{inv_item.item_name}' no longer exists.",
                "error",
            )
            return redirect(url_for("purchase.view_purchase_invoices"))

        removed_qty = inv_item.quantity * factor
        qty_before = itm.quantity
        itm.quantity = qty_before - removed_qty
        itm.cost = inv_item.prev_cost or 0.0

        # Update expected count for the location where items were received
        record = LocationStandItem.query.filter_by(
            location_id=invoice.location_id,
            item_id=itm.id,
        ).first()
        if not record:
            record = LocationStandItem(
                location_id=invoice.location_id,
                item_id=itm.id,
                expected_count=0,
                purchase_gl_code_id=itm.purchase_gl_code_id,
            )
            db.session.add(record)
        elif (
            record.purchase_gl_code_id is None
            and itm.purchase_gl_code_id is not None
        ):
            record.purchase_gl_code_id = itm.purchase_gl_code_id
        new_count = record.expected_count - removed_qty
        record.expected_count = new_count

    loc = db.session.get(Location, invoice.location_id)
    if not loc:
        flash(
            "Cannot reverse invoice because location no longer exists.",
            "error",
        )
        return redirect(url_for("purchase.view_purchase_invoices"))

    PurchaseInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
    db.session.delete(invoice)
    po.received = False
    db.session.commit()
    flash("Invoice reversed successfully", "success")
    return redirect(url_for("purchase.view_purchase_orders"))
