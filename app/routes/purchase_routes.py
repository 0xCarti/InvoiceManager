import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app import db, socketio, GST
from app.utils.activity import log_activity
from app.forms import (
    LocationForm,
    ItemForm,
    TransferForm,
    ImportItemsForm,
    DateRangeForm,
    CustomerForm,
    ProductForm,
    ProductWithRecipeForm,
    ProductRecipeForm,
    InvoiceForm,
    SignupForm,
    LoginForm,
    InvoiceFilterForm,
    PurchaseOrderForm,
    ReceiveInvoiceForm,
    DeleteForm,
    ConfirmForm,
    GLCodeForm,
)
from app.models import (
    Location,
    Item,
    ItemUnit,
    Transfer,
    TransferItem,
    Customer,
    Vendor,
    Product,
    LocationStandItem,
    Invoice,
    InvoiceProduct,
    ProductRecipeItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrderItemArchive,
    GLCode,
)
from datetime import datetime
from app.forms import VendorInvoiceReportForm, ProductSalesReportForm

purchase = Blueprint('purchase', __name__)


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
                location_name = record.location.name if record else db.session.get(Location, invoice_obj.location_id).name
                warnings.append(
                    f"Reversing this invoice will result in negative inventory for {itm.name} at {location_name}"
                )
    return warnings

@purchase.route('/purchase_orders', methods=['GET'])
@login_required
def view_purchase_orders():
    """Show outstanding purchase orders."""
    orders = PurchaseOrder.query.filter_by(received=False).order_by(PurchaseOrder.order_date.desc()).all()
    return render_template('purchase_orders/view_purchase_orders.html', orders=orders)


@purchase.route('/purchase_orders/create', methods=['GET', 'POST'])
@login_required
def create_purchase_order():
    """Create a purchase order."""
    form = PurchaseOrderForm()
    if form.validate_on_submit():
        po = PurchaseOrder(
            vendor_id=form.vendor.data,
            user_id=current_user.id,
            order_date=form.order_date.data,
            expected_date=form.expected_date.data,
            delivery_charge=form.delivery_charge.data or 0.0,
        )
        db.session.add(po)
        db.session.commit()

        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for field in items:
            index = field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item', type=int)
            unit_id = request.form.get(f'items-{index}-unit', type=int)
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            if item_id and quantity is not None:
                db.session.add(PurchaseOrderItem(
                    purchase_order_id=po.id,
                    item_id=item_id,
                    unit_id=unit_id,
                    quantity=quantity
                ))

        db.session.commit()
        log_activity(f'Created purchase order {po.id}')
        flash('Purchase order created successfully!', 'success')
        return redirect(url_for('purchase.view_purchase_orders'))

    return render_template('purchase_orders/create_purchase_order.html', form=form)


@purchase.route('/purchase_orders/edit/<int:po_id>', methods=['GET', 'POST'])
@login_required
def edit_purchase_order(po_id):
    """Modify a pending purchase order."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    form = PurchaseOrderForm()
    if form.validate_on_submit():
        po.vendor_id = form.vendor.data
        po.order_date = form.order_date.data
        po.expected_date = form.expected_date.data
        po.delivery_charge = form.delivery_charge.data or 0.0

        PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).delete()

        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for field in items:
            index = field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item', type=int)
            unit_id = request.form.get(f'items-{index}-unit', type=int)
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            if item_id and quantity is not None:
                db.session.add(PurchaseOrderItem(purchase_order_id=po.id, item_id=item_id, unit_id=unit_id, quantity=quantity))

        db.session.commit()
        log_activity(f'Edited purchase order {po.id}')
        flash('Purchase order updated successfully!', 'success')
        return redirect(url_for('purchase.view_purchase_orders'))

    if request.method == 'GET':
        form.vendor.data = po.vendor_id
        form.order_date.data = po.order_date
        form.expected_date.data = po.expected_date
        form.delivery_charge.data = po.delivery_charge
        form.items.min_entries = max(1, len(po.items))
        for i, poi in enumerate(po.items):
            if len(form.items) <= i:
                form.items.append_entry()
        for item_form in form.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]
        for i, poi in enumerate(po.items):
            form.items[i].item.data = poi.item_id
            form.items[i].unit.data = poi.unit_id
            form.items[i].quantity.data = poi.quantity

    return render_template('purchase_orders/edit_purchase_order.html', form=form, po=po)


@purchase.route('/purchase_orders/<int:po_id>/delete', methods=['GET'])
@login_required
def delete_purchase_order(po_id):
    """Delete an unreceived purchase order."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    if po.received:
        flash('Cannot delete a purchase order that has been received.', 'error')
        return redirect(url_for('purchase.view_purchase_orders'))
    db.session.delete(po)
    db.session.commit()
    log_activity(f'Deleted purchase order {po.id}')
    flash('Purchase order deleted successfully!', 'success')
    return redirect(url_for('purchase.view_purchase_orders'))


@purchase.route('/purchase_orders/<int:po_id>/receive', methods=['GET', 'POST'])
@login_required
def receive_invoice(po_id):
    """Receive a purchase order and create an invoice."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    form = ReceiveInvoiceForm()
    if request.method == 'GET':
        form.delivery_charge.data = po.delivery_charge
        form.items.min_entries = max(1, len(po.items))
        while len(form.items) < len(po.items):
            form.items.append_entry()
        for item_form in form.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]
        for i, poi in enumerate(po.items):
            form.items[i].item.data = poi.item_id
            form.items[i].unit.data = poi.unit_id
            form.items[i].quantity.data = poi.quantity
    if form.validate_on_submit():
        if not PurchaseOrderItemArchive.query.filter_by(purchase_order_id=po.id).first():
            for poi in po.items:
                db.session.add(PurchaseOrderItemArchive(
                    purchase_order_id=po.id,
                    item_id=poi.item_id,
                    unit_id=poi.unit_id,
                    quantity=poi.quantity
                ))
            db.session.commit()
        invoice = PurchaseInvoice(
            purchase_order_id=po.id,
            user_id=current_user.id,
            location_id=form.location_id.data,
            received_date=form.received_date.data,
            invoice_number=form.invoice_number.data,
            gst=form.gst.data or 0.0,
            pst=form.pst.data or 0.0,
            delivery_charge=form.delivery_charge.data or 0.0,
        )
        db.session.add(invoice)
        db.session.commit()

        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for field in items:
            index = field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item', type=int)
            unit_id = request.form.get(f'items-{index}-unit', type=int)
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            cost = request.form.get(f'items-{index}-cost', type=float)
            is_return = request.form.get(f'items-{index}-return_item') is not None
            if item_id and quantity is not None and cost is not None:
                if is_return:
                    quantity = -abs(quantity)
                    cost = -abs(cost)

                item_obj = db.session.get(Item, item_id)
                unit_obj = db.session.get(ItemUnit, unit_id) if unit_id else None

                db.session.add(
                    PurchaseInvoiceItem(
                        invoice_id=invoice.id,
                        item_id=item_obj.id if item_obj else None,
                        unit_id=unit_obj.id if unit_obj else None,
                        item_name=item_obj.name if item_obj else '',
                        unit_name=unit_obj.name if unit_obj else None,
                        quantity=quantity,
                        cost=cost,
                    )
                )

                if item_obj:
                    factor = 1
                    if unit_obj:
                        factor = unit_obj.factor
                    item_obj.quantity = (item_obj.quantity or 0) + quantity * factor
                    # store cost per base unit (always positive)
                    item_obj.cost = abs(cost) / factor if factor else abs(cost)
                    record = LocationStandItem.query.filter_by(location_id=invoice.location_id, item_id=item_obj.id).first()
                    if not record:
                        record = LocationStandItem(location_id=invoice.location_id, item_id=item_obj.id, expected_count=0)
                        db.session.add(record)
                    record.expected_count += quantity * factor

        db.session.commit()
        po.received = True
        db.session.add(po)
        db.session.commit()
        log_activity(f'Received invoice {invoice.id} for PO {po.id}')
        flash('Invoice received successfully!', 'success')
        return redirect(url_for('purchase.view_purchase_invoices'))

    return render_template('purchase_orders/receive_invoice.html', form=form, po=po)


@purchase.route('/purchase_invoices', methods=['GET'])
@login_required
def view_purchase_invoices():
    """List all received purchase invoices."""
    invoices = PurchaseInvoice.query.order_by(PurchaseInvoice.received_date.desc()).all()
    return render_template('purchase_invoices/view_purchase_invoices.html', invoices=invoices)


@purchase.route('/purchase_invoices/<int:invoice_id>')
@login_required
def view_purchase_invoice(invoice_id):
    """Display a purchase invoice."""
    invoice = db.session.get(PurchaseInvoice, invoice_id)
    if invoice is None:
        abort(404)
    return render_template('purchase_invoices/view_purchase_invoice.html', invoice=invoice)


@purchase.route('/purchase_invoices/<int:invoice_id>/report')
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
        if it.item and it.item.purchase_gl_code:
            code = it.item.purchase_gl_code.code
        elif it.item and it.item.purchase_gl_code_id:
            gl = db.session.get(GLCode, it.item.purchase_gl_code_id)
            code = gl.code if gl else None
        if not code:
            code = 'Unassigned'
        gl_totals[code] = gl_totals.get(code, 0) + line_total

    if item_total:
        for code, value in list(gl_totals.items()):
            share = value / item_total
            gl_totals[code] = value + share * invoice.pst + share * invoice.delivery_charge

    if invoice.gst:
        gl_totals['102702'] = gl_totals.get('102702', 0) + invoice.gst

    report = sorted(gl_totals.items())
    return render_template('purchase_invoices/invoice_gl_report.html', invoice=invoice, report=report)


@purchase.route('/purchase_invoices/<int:invoice_id>/reverse', methods=['GET', 'POST'])
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
    if warnings and request.method == 'GET':
        return render_template(
            'confirm_action.html',
            form=form,
            warnings=warnings,
            action_url=url_for('purchase.reverse_purchase_invoice', invoice_id=invoice_id),
            cancel_url=url_for('purchase.view_purchase_invoices'),
            title='Confirm Invoice Reversal',
        )
    if warnings and not form.validate_on_submit():
        return render_template(
            'confirm_action.html',
            form=form,
            warnings=warnings,
            action_url=url_for('purchase.reverse_purchase_invoice', invoice_id=invoice_id),
            cancel_url=url_for('purchase.view_purchase_invoices'),
            title='Confirm Invoice Reversal',
        )
    for inv_item in invoice.items:
        factor = 1
        if inv_item.unit_id:
            unit = db.session.get(ItemUnit, inv_item.unit_id)
            if unit:
                factor = unit.factor
        itm = db.session.get(Item, inv_item.item_id)
        if itm:
            itm.quantity -= inv_item.quantity * factor

            # Revert item cost to the most recent prior purchase invoice
            last_item = (
                db.session.query(PurchaseInvoiceItem)
                .join(PurchaseInvoice)
                .filter(
                    PurchaseInvoiceItem.item_id == itm.id,
                    PurchaseInvoiceItem.invoice_id != invoice.id,
                )
                .order_by(PurchaseInvoice.received_date.desc(), PurchaseInvoice.id.desc())
                .first()
            )
            if last_item:
                last_factor = 1
                if last_item.unit_id:
                    last_unit = db.session.get(ItemUnit, last_item.unit_id)
                    if last_unit:
                        last_factor = last_unit.factor
                itm.cost = abs(last_item.cost) / last_factor if last_factor else abs(last_item.cost)
            else:
                itm.cost = 0.0

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
                )
                db.session.add(record)
            new_count = record.expected_count - inv_item.quantity * factor
            record.expected_count = new_count
    PurchaseInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
    db.session.delete(invoice)
    po.received = False
    db.session.commit()
    flash('Invoice reversed successfully', 'success')
    return redirect(url_for('purchase.view_purchase_orders'))
