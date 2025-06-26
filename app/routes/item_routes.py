from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort
from flask_login import login_required
from werkzeug.utils import secure_filename
from app import db
from app.activity_logger import log_activity
from app.forms import ItemForm, ImportItemsForm, DeleteForm
from app.models import Item, ItemUnit

MAX_IMPORT_SIZE = 1024 * 1024
ALLOWED_IMPORT_EXTENSIONS = {".txt"}

item = Blueprint('item', __name__)
@item.route('/items')
@login_required
def view_items():
    """Display the inventory item list."""
    items = Item.query.all()
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
            return render_template('items/add_item.html', form=form)
        item = Item(
            name=form.name.data,
            base_unit=form.base_unit.data,
            gl_code=form.gl_code.data,
            gl_code_id=form.gl_code_id.data,
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
    return render_template('items/add_item.html', form=form)


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
        for idx, unit in enumerate(item.units):
            if idx < len(form.units):
                form.units[idx].form.name.data = unit.name
                form.units[idx].form.factor.data = unit.factor
                form.units[idx].form.receiving_default.data = unit.receiving_default
                form.units[idx].form.transfer_default.data = unit.transfer_default
            else:
                form.units.append_entry({
                    'name': unit.name,
                    'factor': unit.factor,
                    'receiving_default': unit.receiving_default,
                    'transfer_default': unit.transfer_default
                })
    if form.validate_on_submit():
        recv_count = sum(1 for uf in form.units if uf.form.name.data and uf.form.receiving_default.data)
        trans_count = sum(1 for uf in form.units if uf.form.name.data and uf.form.transfer_default.data)
        if recv_count > 1 or trans_count > 1:
            flash('Only one unit can be set as receiving and transfer default.', 'error')
            return render_template('items/edit_item.html', form=form, item=item)
        item.name = form.name.data
        item.base_unit = form.base_unit.data
        item.gl_code = form.gl_code.data
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
    return render_template('items/edit_item.html', form=form, item=item)


@item.route('/items/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete an item from the catalog."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    log_activity(f'Deleted item {item.id}')
    flash('Item deleted successfully!')
    return redirect(url_for('item.view_items'))


@item.route('/items/bulk_delete', methods=['POST'])
@login_required
def bulk_delete_items():
    """Delete multiple items in one request."""
    item_ids = request.form.getlist('item_ids')
    if item_ids:
        Item.query.filter(Item.id.in_(item_ids)).delete(synchronize_session='fetch')
        db.session.commit()
        log_activity(f'Bulk deleted items {",".join(item_ids)}')
        flash('Selected items have been deleted.', 'success')
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
                    # Check if item already exists to avoid duplicates
                    existing_item = Item.query.filter_by(name=item_name).first()
                    if not existing_item:
                        # Create a new item instance and add it to the database
                        new_item = Item(name=item_name)
                        db.session.add(new_item)
        db.session.commit()
        log_activity('Imported items from file')

        flash('Items imported successfully.', 'success')
        return redirect(url_for('item.import_items'))

    return render_template('items/import_items.html', form=form)
