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

transfer = Blueprint('transfer', __name__)


def check_negative_transfer(transfer_obj, multiplier=1):
    """Return warnings if a transfer would cause negative inventory."""
    warnings = []
    for ti in transfer_obj.transfer_items:
        from_record = LocationStandItem.query.filter_by(
            location_id=transfer_obj.from_location_id,
            item_id=ti.item_id
        ).first()
        current_from = from_record.expected_count if from_record else 0
        new_from = current_from - multiplier * ti.quantity
        if new_from < 0:
            item = db.session.get(Item, ti.item_id)
            item_name = item.name if item else ti.item_name
            from_name = transfer_obj.from_location.name if transfer_obj.from_location else transfer_obj.from_location_name
            warnings.append(
                f"Transfer will result in negative inventory for {item_name} at {from_name}"
            )

        to_record = LocationStandItem.query.filter_by(
            location_id=transfer_obj.to_location_id,
            item_id=ti.item_id
        ).first()
        current_to = to_record.expected_count if to_record else 0
        new_to = current_to + multiplier * ti.quantity
        if new_to < 0:
            item = db.session.get(Item, ti.item_id)
            item_name = item.name if item else ti.item_name
            to_name = transfer_obj.to_location.name if transfer_obj.to_location else transfer_obj.to_location_name
            warnings.append(
                f"Transfer will result in negative inventory for {item_name} at {to_name}"
            )
    return warnings


def update_expected_counts(transfer_obj, multiplier=1):
    """Update expected counts for locations involved in a transfer."""
    for ti in transfer_obj.transfer_items:
        from_record = LocationStandItem.query.filter_by(
            location_id=transfer_obj.from_location_id,
            item_id=ti.item_id
        ).first()
        if not from_record:
            from_record = LocationStandItem(
                location_id=transfer_obj.from_location_id,
                item_id=ti.item_id,
                expected_count=0
            )
            db.session.add(from_record)
        new_from = from_record.expected_count - multiplier * ti.quantity
        from_record.expected_count = new_from

        to_record = LocationStandItem.query.filter_by(
            location_id=transfer_obj.to_location_id,
            item_id=ti.item_id
        ).first()
        if not to_record:
            to_record = LocationStandItem(
                location_id=transfer_obj.to_location_id,
                item_id=ti.item_id,
                expected_count=0
            )
            db.session.add(to_record)
        new_to = to_record.expected_count + multiplier * ti.quantity
        to_record.expected_count = new_to

@transfer.route('/transfers', methods=['GET'])
@login_required
def view_transfers():
    """Show transfers with optional filtering."""
    filter_option = request.args.get('filter', 'not_completed')
    transfer_id = request.args.get('transfer_id', '', type=int)  # Optional: Search by Transfer ID
    from_location_name = request.args.get('from_location', '')  # Optional: Search by From Location
    to_location_name = request.args.get('to_location', '')  # Optional: Search by To Location

    query = Transfer.query
    if transfer_id != '':
        query = query.filter(Transfer.id == transfer_id)

    if from_location_name != '':
        query = query.join(Location, Transfer.from_location_id == Location.id).filter(
            Location.name.ilike(f"%{from_location_name}%"))

    if to_location_name != '':
        query = query.join(Location, Transfer.to_location_id == Location.id).filter(
            Location.name.ilike(f"%{to_location_name}%"))

    if filter_option == 'completed':
        transfers = query.filter(Transfer.completed == True).all()
    elif filter_option == 'not_completed':
        transfers = query.filter(Transfer.completed == False).all()
    else:
        transfers = query.all()

    form = TransferForm()  # Assuming you're using it for something like a filter form on the page
    return render_template('transfers/view_transfers.html', transfers=transfers, form=form)


@transfer.route('/transfers/add', methods=['GET', 'POST'])
@login_required
def add_transfer():
    """Create a transfer between locations."""
    form = TransferForm()
    if form.validate_on_submit():
        transfer = Transfer(
            from_location_id=form.from_location_id.data,
            to_location_id=form.to_location_id.data,
            user_id=current_user.id,
            from_location_name=db.session.get(Location, form.from_location_id.data).name,
            to_location_name=db.session.get(Location, form.to_location_id.data).name
        )
        db.session.add(transfer)
        # Dynamically determine the number of items added
        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for item_field in items:
            index = item_field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item')
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            unit_id = request.form.get(f'items-{index}-unit', type=int)
            if item_id:
                item = db.session.get(Item, item_id)
                if item and quantity is not None:
                    factor = 1
                    if unit_id:
                        unit = db.session.get(ItemUnit, unit_id)
                        if unit:
                            factor = unit.factor
                    transfer_item = TransferItem(
                        transfer_id=transfer.id,
                        item_id=item.id,
                        quantity=quantity * factor,
                        item_name=item.name
                    )
                    db.session.add(transfer_item)
        db.session.commit()
        log_activity(f'Added transfer {transfer.id}')

        socketio.emit('new_transfer', {'message': 'New transfer added'})

        flash('Transfer added successfully!', 'success')
        return redirect(url_for('transfer.view_transfers'))
    elif form.errors:
        flash('There was an error submitting the transfer.', 'error')

    return render_template('transfers/add_transfer.html', form=form)


@transfer.route('/transfers/edit/<int:transfer_id>', methods=['GET', 'POST'])
@login_required
def edit_transfer(transfer_id):
    """Update an existing transfer."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    form = TransferForm(obj=transfer)

    if form.validate_on_submit():
        transfer.from_location_id = form.from_location_id.data
        transfer.to_location_id = form.to_location_id.data
        transfer.from_location_name = db.session.get(Location, form.from_location_id.data).name
        transfer.to_location_name = db.session.get(Location, form.to_location_id.data).name

        # Clear existing TransferItem entries
        TransferItem.query.filter_by(transfer_id=transfer.id).delete()

        # Dynamically determine the number of items added, similar to the "add" route
        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for item_field in items:
            index = item_field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item')
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            unit_id = request.form.get(f'items-{index}-unit', type=int)
            if item_id and quantity is not None:  # Ensure both are provided and valid
                factor = 1
                if unit_id:
                    unit = db.session.get(ItemUnit, unit_id)
                    if unit:
                        factor = unit.factor
                new_transfer_item = TransferItem(
                    transfer_id=transfer.id,
                    item_id=int(item_id),
                    quantity=quantity * factor,
                    item_name=db.session.get(Item, int(item_id)).name
                )
                db.session.add(new_transfer_item)

        db.session.commit()
        log_activity(f'Edited transfer {transfer.id}')
        flash('Transfer updated successfully!', 'success')
        return redirect(url_for('transfer.view_transfers'))
    elif form.errors:
        flash('There was an error submitting the transfer.', 'error')

    # For GET requests or if the form doesn't validate, pass existing items to the template
    items = [{"id": item.item_id, "name": item.item.name, "quantity": item.quantity} for item in
             transfer.transfer_items]
    return render_template('transfers/edit_transfer.html', form=form, transfer=transfer, items=items)


@transfer.route('/transfers/delete/<int:transfer_id>', methods=['POST'])
@login_required
def delete_transfer(transfer_id):
    """Permanently remove a transfer."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    if transfer.completed:
        update_expected_counts(transfer, multiplier=-1)
    db.session.delete(transfer)
    db.session.commit()
    log_activity(f'Deleted transfer {transfer.id}')
    flash('Transfer deleted successfully!', 'success')
    return redirect(url_for('transfer.view_transfers'))


@transfer.route('/transfers/complete/<int:transfer_id>', methods=['GET', 'POST'])
@login_required
def complete_transfer(transfer_id):
    """Mark a transfer as completed."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    warnings = check_negative_transfer(transfer, multiplier=1)
    form = ConfirmForm()
    if warnings and request.method == 'GET':
        return render_template(
            'confirm_action.html',
            form=form,
            warnings=warnings,
            action_url=url_for('transfer.complete_transfer', transfer_id=transfer_id),
            cancel_url=url_for('transfer.view_transfers'),
            title='Confirm Transfer Completion',
        )
    if warnings and not form.validate_on_submit():
        return render_template(
            'confirm_action.html',
            form=form,
            warnings=warnings,
            action_url=url_for('transfer.complete_transfer', transfer_id=transfer_id),
            cancel_url=url_for('transfer.view_transfers'),
            title='Confirm Transfer Completion',
        )
    transfer.completed = True
    update_expected_counts(transfer, multiplier=1)
    db.session.commit()
    log_activity(f'Completed transfer {transfer.id}')
    flash('Transfer marked as complete!', 'success')
    return redirect(url_for('transfer.view_transfers'))


@transfer.route('/transfers/uncomplete/<int:transfer_id>', methods=['GET', 'POST'])
@login_required
def uncomplete_transfer(transfer_id):
    """Revert a transfer to not completed."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    warnings = check_negative_transfer(transfer, multiplier=-1)
    form = ConfirmForm()
    if warnings and request.method == 'GET':
        return render_template(
            'confirm_action.html',
            form=form,
            warnings=warnings,
            action_url=url_for('transfer.uncomplete_transfer', transfer_id=transfer_id),
            cancel_url=url_for('transfer.view_transfers'),
            title='Confirm Transfer Incomplete',
        )
    if warnings and not form.validate_on_submit():
        return render_template(
            'confirm_action.html',
            form=form,
            warnings=warnings,
            action_url=url_for('transfer.uncomplete_transfer', transfer_id=transfer_id),
            cancel_url=url_for('transfer.view_transfers'),
            title='Confirm Transfer Incomplete',
        )
    transfer.completed = False
    update_expected_counts(transfer, multiplier=-1)
    db.session.commit()
    log_activity(f'Uncompleted transfer {transfer.id}')
    flash('Transfer marked as not completed.', 'success')
    return redirect(url_for('transfer.view_transfers'))

@transfer.route('/transfers/view/<int:transfer_id>', methods=['GET'])
@login_required
def view_transfer(transfer_id):
    """Show details for a single transfer."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    transfer_items = TransferItem.query.filter_by(transfer_id=transfer.id).all()
    return render_template('transfers/view_transfer.html', transfer=transfer, transfer_items=transfer_items)


@transfer.route('/transfers/generate_report', methods=['GET', 'POST'])
def generate_report():
    """Generate a transfer summary over a date range."""
    form = DateRangeForm()
    if form.validate_on_submit():
        start_datetime = form.start_datetime.data
        end_datetime = form.end_datetime.data

        # Alias for "from" and "to" locations
        from_location = db.aliased(Location)
        to_location = db.aliased(Location)

        aggregated_transfers = db.session.query(
            from_location.name.label('from_location_name'),
            to_location.name.label('to_location_name'),
            Item.name.label('item_name'),
            func.sum(TransferItem.quantity).label('total_quantity')
        ).select_from(Transfer) \
            .join(TransferItem, Transfer.id == TransferItem.transfer_id) \
            .join(Item, TransferItem.item_id == Item.id) \
            .join(from_location, Transfer.from_location_id == from_location.id) \
            .join(to_location, Transfer.to_location_id == to_location.id) \
            .filter(
            Transfer.completed == True,
            Transfer.date_created >= start_datetime,
            Transfer.date_created <= end_datetime
        ) \
            .group_by(
            from_location.name,
            to_location.name,
            Item.name
        ) \
            .order_by(
            from_location.name,
            to_location.name,
            Item.name
        ) \
            .all()

        # Process the results for display or session storage
        session['aggregated_transfers'] = [{
            'from_location_name': result[0],
            'to_location_name': result[1],
            'item_name': result[2],
            'total_quantity': result[3]
        } for result in aggregated_transfers]

        # Store start and end date/time in session for use in the report
        session['report_start_datetime'] = start_datetime.strftime('%Y-%m-%d %H:%M')
        session['report_end_datetime'] = end_datetime.strftime('%Y-%m-%d %H:%M')

        flash('Transfer report generated successfully.', 'success')
        return redirect(url_for('transfer.view_report'))

    return render_template('transfers/generate_report.html', form=form)


@transfer.route('/transfers/report')
def view_report():
    """Display the previously generated transfer report."""
    aggregated_transfers = session.get('aggregated_transfers', [])
    return render_template('transfers/view_report.html', aggregated_transfers=aggregated_transfers)
