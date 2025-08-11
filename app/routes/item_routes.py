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

item = Blueprint('item', __name__)

# Constants for the import_items route
# Only plain text files are allowed and uploads are capped at 1MB
ALLOWED_IMPORT_EXTENSIONS = {'.txt'}
MAX_IMPORT_SIZE = 1 * 1024 * 1024  # 1 MB

@item.route('/items')
@login_required
def view_items():
    """Display the inventory item list."""
    items = Item.query.filter_by(archived=False).all()
    form = ItemForm()
    return render_template('items/view_items.html', items=items, form=form)


@item.route('/items/add', methods=['GET', 'POST'])
@login_required
def add_item():
    """Add a new item to inventory."""
    form = ItemForm()
    if form.validate_on_submit():
        recv_count = sum(1 for uf in form.units if uf.form.name.data and uf.form.receiving_default.data)
        trans_count = sum(1 for uf in form.units if uf.form.name.data and uf.form.transfer_default.data)
        if recv_count > 1 or trans_count > 1:
            flash('Only one unit can be set as receiving and transfer default.', 'error')
            return render_template('items/item_form.html', form=form, title='Add Item')
        item = Item(
            name=form.name.data,
            base_unit=form.base_unit.data,
            gl_code=form.gl_code.data if 'gl_code' in request.form else None,
            gl_code_id=form.gl_code_id.data if 'gl_code_id' in request.form else None,
            purchase_gl_code_id=form.purchase_gl_code.data or None,
        )
        db.session.add(item)
        db.session.commit()
        receiving_set = False
        transfer_set = False
        for uf in form.units:
            unit_form = uf.form
            if unit_form.name.data:
                receiving_default = unit_form.receiving_default.data and not receiving_set
                transfer_default = unit_form.transfer_default.data and not transfer_set
                db.session.add(ItemUnit(
                    item_id=item.id,
                    name=unit_form.name.data,
                    factor=float(unit_form.factor.data),
                    receiving_default=receiving_default,
                    transfer_default=transfer_default
                ))
                if receiving_default:
                    receiving_set = True
                if transfer_default:
                    transfer_set = True
        db.session.commit()
        log_activity(f'Added item {item.name}')
        flash('Item added successfully!')
        return redirect(url_for('item.view_items'))
    return render_template('items/item_form.html', form=form, title='Add Item')


@item.route('/items/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    """Modify an existing item."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    form = ItemForm(obj=item)
    if request.method == 'GET':
        form.gl_code.data = item.gl_code
        form.gl_code_id.data = item.gl_code_id
        form.purchase_gl_code.data = item.purchase_gl_code_id
    if form.validate_on_submit():
        recv_count = sum(1 for uf in form.units if uf.form.name.data and uf.form.receiving_default.data)
        trans_count = sum(1 for uf in form.units if uf.form.name.data and uf.form.transfer_default.data)
        if recv_count > 1 or trans_count > 1:
            flash('Only one unit can be set as receiving and transfer default.', 'error')
            return render_template('items/item_form.html', form=form, item=item, title='Edit Item')
        item.name = form.name.data
        item.base_unit = form.base_unit.data
        if 'gl_code' in request.form:
            item.gl_code = form.gl_code.data
        if 'gl_code_id' in request.form:
            item.gl_code_id = form.gl_code_id.data
        item.purchase_gl_code_id = form.purchase_gl_code.data or None
        ItemUnit.query.filter_by(item_id=item.id).delete()
        receiving_set = False
        transfer_set = False
        for uf in form.units:
            unit_form = uf.form
            if unit_form.name.data:
                receiving_default = unit_form.receiving_default.data and not receiving_set
                transfer_default = unit_form.transfer_default.data and not transfer_set
                db.session.add(ItemUnit(
                    item_id=item.id,
                    name=unit_form.name.data,
                    factor=float(unit_form.factor.data),
                    receiving_default=receiving_default,
                    transfer_default=transfer_default
                ))
                if receiving_default:
                    receiving_set = True
                if transfer_default:
                    transfer_set = True
        db.session.commit()
        log_activity(f'Edited item {item.id}')
        flash('Item updated successfully!')
        return redirect(url_for('item.view_items'))
    return render_template('items/item_form.html', form=form, item=item, title='Edit Item')


@item.route('/items/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete an item from the catalog."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    item.archived = True
    db.session.commit()
    log_activity(f'Archived item {item.id}')
    flash('Item archived successfully!')
    return redirect(url_for('item.view_items'))


@item.route('/items/bulk_delete', methods=['POST'])
@login_required
def bulk_delete_items():
    """Delete multiple items in one request."""
    item_ids = request.form.getlist('item_ids')
    if item_ids:
        Item.query.filter(Item.id.in_(item_ids)).update({'archived': True}, synchronize_session='fetch')
        db.session.commit()
        log_activity(f'Bulk archived items {",".join(item_ids)}')
        flash('Selected items have been archived.', 'success')
    else:
        flash('No items selected.', 'warning')
    return redirect(url_for('item.view_items'))

@item.route('/items/search', methods=['GET'])
@login_required
def search_items():
    """Search items by name for autocomplete fields."""
    search_term = request.args.get('term', '')
    items = Item.query.filter(Item.name.ilike(f'%{search_term}%')).all()
    items_data = [{'id': item.id, 'name': item.name} for item in items]  # Create a list of dicts
    return jsonify(items_data)


@item.route('/items/quick_add', methods=['POST'])
@login_required
def quick_add_item():
    """Create a minimal item via AJAX for purchase orders."""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    base_unit = data.get('base_unit')
    valid_units = {'ounce', 'gram', 'each', 'millilitre'}
    if not name or base_unit not in valid_units:
        return jsonify({'error': 'Invalid data'}), 400
    if Item.query.filter_by(name=name, archived=False).first():
        return jsonify({'error': 'Item exists'}), 400
    item = Item(name=name, base_unit=base_unit)
    db.session.add(item)
    db.session.commit()
    unit = ItemUnit(
        item_id=item.id,
        name=base_unit,
        factor=1,
        receiving_default=True,
        transfer_default=True,
    )
    db.session.add(unit)
    db.session.commit()
    log_activity(f'Added item {item.name}')
    return jsonify({'id': item.id, 'name': item.name})


@item.route('/items/<int:item_id>/units')
@login_required
def item_units(item_id):
    """Return unit options for an item."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    data = [
        {
            'id': u.id,
            'name': u.name,
            'factor': u.factor,
            'receiving_default': u.receiving_default,
            'transfer_default': u.transfer_default,
        }
        for u in item.units
    ]
    return jsonify(data)


@item.route('/items/<int:item_id>/last_cost')
@login_required
def item_last_cost(item_id):
    """Return the last recorded cost for an item."""
    unit_id = request.args.get('unit_id', type=int)
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    factor = 1.0
    if unit_id:
        unit = db.session.get(ItemUnit, unit_id)
        if unit:
            factor = unit.factor
    return jsonify({'cost': (item.cost or 0.0) * factor})


@item.route('/import_items', methods=['GET', 'POST'])
@login_required
def import_items():
    """Bulk import items from a text file."""
    form = ImportItemsForm()
    if form.validate_on_submit():
        from run import app

        file = form.file.data
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if ext not in ALLOWED_IMPORT_EXTENSIONS:
            flash('Only .txt files are allowed.', 'error')
            return redirect(url_for('item.import_items'))
        if size > MAX_IMPORT_SIZE:
            flash('File is too large.', 'error')
            return redirect(url_for('item.import_items'))
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Parse the file
        with open(filepath, 'r') as file:
            for line in file:
                item_name = line.strip()
                if item_name:
                    # Check if an active item already exists to avoid duplicates
                    existing_item = Item.query.filter_by(name=item_name, archived=False).first()
                    if not existing_item:
                        # Create a new item instance and add it to the database
                        new_item = Item(name=item_name)
                        db.session.add(new_item)
        db.session.commit()
        log_activity('Imported items from file')

        flash('Items imported successfully.', 'success')
        return redirect(url_for('item.import_items'))

    return render_template('items/import_items.html', form=form)

