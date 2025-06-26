import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
from app import db, socketio, GST
from app.activity_logger import log_activity
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
from flask import Blueprint, render_template
from app.forms import VendorInvoiceReportForm, ProductSalesReportForm
MAX_IMPORT_SIZE = 1024 * 1024
ALLOWED_IMPORT_EXTENSIONS = {".txt"}


# If you're not already using a Blueprint for your main routes, create one.
main = Blueprint('main', __name__)
location = Blueprint('locations', __name__)
item = Blueprint('item', __name__)
transfer = Blueprint('transfer', __name__)
product = Blueprint('product', __name__)
customer = Blueprint('customer', __name__)
invoice = Blueprint('invoice', __name__)
report = Blueprint('report', __name__)
purchase = Blueprint('purchase', __name__)
vendor = Blueprint('vendor', __name__)
glcode_bp = Blueprint('glcode', __name__)


def update_expected_counts(transfer, multiplier=1):
    """Update expected counts for locations involved in a transfer."""
    for ti in transfer.transfer_items:
        from_record = LocationStandItem.query.filter_by(
            location_id=transfer.from_location_id,
            item_id=ti.item_id
        ).first()
        if not from_record:
            from_record = LocationStandItem(
                location_id=transfer.from_location_id,
                item_id=ti.item_id,
                expected_count=0
            )
            db.session.add(from_record)
        from_record.expected_count -= multiplier * ti.quantity

        to_record = LocationStandItem.query.filter_by(
            location_id=transfer.to_location_id,
            item_id=ti.item_id
        ).first()
        if not to_record:
            to_record = LocationStandItem(
                location_id=transfer.to_location_id,
                item_id=ti.item_id,
                expected_count=0
            )
            db.session.add(to_record)
        to_record.expected_count += multiplier * ti.quantity


@main.route('/')
@login_required
def home():
    """Render the transfers dashboard."""
    return render_template('transfers/view_transfers.html', user=current_user)


@location.route('/locations/add', methods=['GET', 'POST'])
@login_required
def add_location():
    """Create a new location."""
    form = LocationForm()
    if form.validate_on_submit():
        new_location = Location(name=form.name.data)
        product_ids = [int(pid) for pid in form.products.data.split(',') if pid] if form.products.data else []
        selected_products = [db.session.get(Product, pid) for pid in product_ids]
        new_location.products = selected_products
        db.session.add(new_location)
        db.session.commit()

        # Add stand sheet items for countable recipe items
        for product_obj in selected_products:
            for recipe_item in product_obj.recipe_items:
                if recipe_item.countable:
                    exists = LocationStandItem.query.filter_by(
                        location_id=new_location.id,
                        item_id=recipe_item.item_id
                    ).first()
                    if not exists:
                        db.session.add(LocationStandItem(location_id=new_location.id, item_id=recipe_item.item_id, expected_count=0))
        db.session.commit()
        log_activity(f'Added location {new_location.name}')
        flash('Location added successfully!')
        return redirect(url_for('locations.view_locations'))
    selected_products = []
    if form.products.data:
        ids = [int(pid) for pid in form.products.data.split(',') if pid]
        selected_products = Product.query.filter(Product.id.in_(ids)).all()
    selected_data = [{'id': p.id, 'name': p.name} for p in selected_products]
    return render_template('locations/add_location.html', form=form,
                           selected_products=selected_data)


@location.route('/locations/edit/<int:location_id>', methods=['GET', 'POST'])
@login_required
def edit_location(location_id):
    """Edit an existing location."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    form = LocationForm(obj=location)
    if request.method == 'GET':
        form.products.data = ','.join(str(p.id) for p in location.products)

    if form.validate_on_submit():
        location.name = form.name.data
        product_ids = [int(pid) for pid in form.products.data.split(',') if pid] if form.products.data else []
        selected_products = [db.session.get(Product, pid) for pid in product_ids]
        location.products = selected_products
        db.session.commit()

        # Ensure stand sheet items exist for new products
        for product_obj in selected_products:
            for recipe_item in product_obj.recipe_items:
                if recipe_item.countable:
                    exists = LocationStandItem.query.filter_by(
                        location_id=location.id,
                        item_id=recipe_item.item_id
                    ).first()
                    if not exists:
                        db.session.add(LocationStandItem(location_id=location.id, item_id=recipe_item.item_id, expected_count=0))
        db.session.commit()
        log_activity(f'Edited location {location.id}')
        flash('Location updated successfully.', 'success')
        return redirect(url_for('locations.edit_location', location_id=location.id))

    # Query for completed transfers to this location
    transfers_to_location = Transfer.query.filter_by(to_location_id=location_id, completed=True).all()

    selected_data = [{'id': p.id, 'name': p.name} for p in location.products]
    return render_template('locations/edit_location.html', form=form, location=location,
                           transfers=transfers_to_location,
                           selected_products=selected_data)


@location.route('/locations/<int:location_id>/stand_sheet')
@login_required
def view_stand_sheet(location_id):
    """Display the expected item counts for a location."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)

    stand_items = []
    seen = set()
    for product_obj in location.products:
        for recipe_item in product_obj.recipe_items:
            if recipe_item.countable and recipe_item.item_id not in seen:
                seen.add(recipe_item.item_id)
                record = LocationStandItem.query.filter_by(
                    location_id=location_id, item_id=recipe_item.item_id
                ).first()
                expected = record.expected_count if record else 0
                stand_items.append({'item': recipe_item.item, 'expected': expected})

    return render_template('locations/stand_sheet.html', location=location, stand_items=stand_items)


@location.route('/locations')
@login_required
def view_locations():
    """List all locations."""
    locations = Location.query.all()
    delete_form = DeleteForm()
    return render_template('locations/view_locations.html', locations=locations, delete_form=delete_form)


@location.route('/locations/delete/<int:location_id>', methods=['POST'])
@login_required
def delete_location(location_id):
    """Remove a location from the database."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    db.session.delete(location)
    db.session.commit()
    log_activity(f'Deleted location {location.id}')
    flash('Location deleted successfully!')
    return redirect(url_for('locations.view_locations'))


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
            user_id=current_user.id
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
                        quantity=quantity * factor
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
                    quantity=quantity * factor
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


@transfer.route('/transfers/complete/<int:transfer_id>', methods=['GET'])
@login_required
def complete_transfer(transfer_id):
    """Mark a transfer as completed."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    transfer.completed = True
    update_expected_counts(transfer, multiplier=1)
    db.session.commit()
    log_activity(f'Completed transfer {transfer.id}')
    flash('Transfer marked as complete!', 'success')
    return redirect(url_for('transfer.view_transfers'))


@transfer.route('/transfers/uncomplete/<int:transfer_id>', methods=['GET'])
@login_required
def uncomplete_transfer(transfer_id):
    """Revert a transfer to not completed."""
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
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


@product.route('/products')
@login_required
def view_products():
    """List available products."""
    products = Product.query.all()
    return render_template('view_products.html', products=products)


@product.route('/products/create', methods=['GET', 'POST'])
@login_required
def create_product():
    """Add a new product definition."""
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        product = Product(
            name=form.name.data,
            price=form.price.data,
            cost=form.cost.data,  # Save cost
            gl_code=form.gl_code.data,
            gl_code_id=form.gl_code_id.data,
            sales_gl_code_id=form.sales_gl_code.data or None,
        )
        if not product.gl_code and product.gl_code_id:
            gl = db.session.get(GLCode, product.gl_code_id)
            if gl:
                product.gl_code = gl.code
        db.session.add(product)
        db.session.commit()

        for item_form in form.items:
            item_id = item_form.item.data
            quantity = item_form.quantity.data
            countable = item_form.countable.data
            if item_id and quantity is not None:
                db.session.add(
                    ProductRecipeItem(
                        product_id=product.id,
                        item_id=item_id,
                        quantity=quantity,
                        countable=countable,
                    )
                )
        db.session.commit()
        log_activity(f'Created product {product.name}')
        flash('Product created successfully!', 'success')
        return redirect(url_for('product.view_products'))
    return render_template('create_product.html', form=form, product_id=None)


@product.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    """Edit product details and recipe."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        product.name = form.name.data
        product.price = form.price.data
        product.cost = form.cost.data or 0.0  # 👈 Update cost
        product.gl_code = form.gl_code.data
        product.gl_code_id = form.gl_code_id.data
        product.sales_gl_code_id = form.sales_gl_code.data or None
        if not product.gl_code and product.gl_code_id:
            gl = db.session.get(GLCode, product.gl_code_id)
            if gl:
                product.gl_code = gl.code

        ProductRecipeItem.query.filter_by(product_id=product.id).delete()
        for item_form in form.items:
            item_id = item_form.item.data
            quantity = item_form.quantity.data
            countable = item_form.countable.data
            if item_id and quantity is not None:
                db.session.add(
                    ProductRecipeItem(
                        product_id=product.id,
                        item_id=item_id,
                        quantity=quantity,
                        countable=countable,
                    )
                )
        db.session.commit()
        log_activity(f'Edited product {product.id}')
        flash('Product updated successfully!', 'success')
        return redirect(url_for('product.view_products'))
    elif request.method == 'GET':
        form.name.data = product.name
        form.price.data = product.price
        form.cost.data = product.cost or 0.0  # 👈 Pre-fill cost
        form.gl_code.data = product.gl_code
        form.gl_code_id.data = product.gl_code_id
        form.sales_gl_code.data = product.sales_gl_code_id
        form.items.min_entries = max(1, len(product.recipe_items))
        item_choices = [(itm.id, itm.name) for itm in Item.query.all()]
        for i, recipe_item in enumerate(product.recipe_items):
            if len(form.items) <= i:
                form.items.append_entry()
                form.items[i].item.choices = item_choices
            else:
                form.items[i].item.choices = item_choices
            form.items[i].item.data = recipe_item.item_id
            form.items[i].quantity.data = recipe_item.quantity
            form.items[i].countable.data = recipe_item.countable
    else:
        print(form.errors)
        print(form.cost.data)
    return render_template('edit_product.html', form=form, product_id=product.id)


@product.route('/products/<int:product_id>/recipe', methods=['GET', 'POST'])
@login_required
def edit_product_recipe(product_id):
    """Edit the recipe for a product."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    form = ProductRecipeForm()
    if form.validate_on_submit():
        ProductRecipeItem.query.filter_by(product_id=product.id).delete()
        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for field in items:
            index = field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item', type=int)
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            countable = request.form.get(f'items-{index}-countable') == 'y'
            if item_id and quantity is not None:
                db.session.add(ProductRecipeItem(product_id=product.id, item_id=item_id, quantity=quantity, countable=countable))
        db.session.commit()
        flash('Recipe updated successfully!', 'success')
        return redirect(url_for('product.view_products'))
    elif request.method == 'GET':
        form.items.min_entries = max(1, len(product.recipe_items))
        item_choices = [(itm.id, itm.name) for itm in Item.query.all()]
        for i, recipe_item in enumerate(product.recipe_items):
            if len(form.items) <= i:
                form.items.append_entry()
                form.items[i].item.choices = item_choices
            else:
                form.items[i].item.choices = item_choices
            form.items[i].item.data = recipe_item.item_id
            form.items[i].quantity.data = recipe_item.quantity
            form.items[i].countable.data = recipe_item.countable
    return render_template('edit_product_recipe.html', form=form, product=product)


@product.route('/products/<int:product_id>/calculate_cost')
@login_required
def calculate_product_cost(product_id):
    """Calculate the total recipe cost for a product."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    total = 0.0
    for ri in product.recipe_items:
        item_cost = getattr(ri.item, 'cost', 0.0)
        try:
            qty = float(ri.quantity or 0)
        except (TypeError, ValueError):
            qty = 0
        total += (item_cost or 0) * qty
    return jsonify({'cost': total})


@product.route('/products/<int:product_id>/delete', methods=['GET'])
@login_required
def delete_product(product_id):
    """Delete a product and its recipe."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    db.session.delete(product)
    db.session.commit()
    log_activity(f'Deleted product {product.id}')
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('product.view_products'))


@customer.route('/customers')
@login_required
def view_customers():
    """Display all customers."""
    customers = Customer.query.all()
    return render_template('view_customers.html', customers=customers)


@customer.route('/customers/create', methods=['GET', 'POST'])
@login_required
def create_customer():
    """Add a customer record."""
    form = CustomerForm()
    if form.validate_on_submit():
        customer = Customer(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            gst_exempt=form.gst_exempt.data,
            pst_exempt=form.pst_exempt.data
        )
        db.session.add(customer)
        db.session.commit()
        log_activity(f'Created customer {customer.id}')
        flash('Customer created successfully!', 'success')
        return redirect(url_for('customer.view_customers'))
    return render_template('create_customer.html', form=form)


@customer.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    """Edit customer details."""
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    form = CustomerForm()

    if form.validate_on_submit():
        customer.first_name = form.first_name.data
        customer.last_name = form.last_name.data
        customer.gst_exempt = form.gst_exempt.data
        customer.pst_exempt = form.pst_exempt.data
        db.session.commit()
        log_activity(f'Edited customer {customer.id}')
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('customer.view_customers'))

    elif request.method == 'GET':
        form.first_name.data = customer.first_name
        form.last_name.data = customer.last_name
        form.gst_exempt.data = customer.gst_exempt
        form.pst_exempt.data = customer.pst_exempt

    return render_template('edit_customer.html', form=form)


@customer.route('/customers/<int:customer_id>/delete', methods=['GET'])
@login_required
def delete_customer(customer_id):
    """Delete a customer."""
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    db.session.delete(customer)
    db.session.commit()
    log_activity(f'Deleted customer {customer.id}')
    flash('Customer deleted successfully!', 'success')
    return redirect(url_for('customer.view_customers'))


@vendor.route('/vendors')
@login_required
def view_vendors():
    """Display all vendors."""
    vendors = Customer.query.all()
    return render_template('view_vendors.html', vendors=vendors)


@vendor.route('/vendors/create', methods=['GET', 'POST'])
@login_required
def create_vendor():
    """Create a new vendor."""
    form = CustomerForm()
    if form.validate_on_submit():
        vendor = Customer(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            gst_exempt=form.gst_exempt.data,
            pst_exempt=form.pst_exempt.data
        )
        db.session.add(vendor)
        db.session.commit()
        log_activity(f'Created vendor {vendor.id}')
        flash('Vendor created successfully!', 'success')
        return redirect(url_for('vendor.view_vendors'))
    return render_template('create_vendor.html', form=form)


@vendor.route('/vendors/<int:vendor_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_vendor(vendor_id):
    """Edit vendor information."""
    vendor = db.session.get(Customer, vendor_id)
    if vendor is None:
        abort(404)
    form = CustomerForm()

    if form.validate_on_submit():
        vendor.first_name = form.first_name.data
        vendor.last_name = form.last_name.data
        vendor.gst_exempt = form.gst_exempt.data
        vendor.pst_exempt = form.pst_exempt.data
        db.session.commit()
        log_activity(f'Edited vendor {vendor.id}')
        flash('Vendor updated successfully!', 'success')
        return redirect(url_for('vendor.view_vendors'))

    elif request.method == 'GET':
        form.first_name.data = vendor.first_name
        form.last_name.data = vendor.last_name
        form.gst_exempt.data = vendor.gst_exempt
        form.pst_exempt.data = vendor.pst_exempt

    return render_template('edit_vendor.html', form=form)


@vendor.route('/vendors/<int:vendor_id>/delete', methods=['GET'])
@login_required
def delete_vendor(vendor_id):
    """Remove a vendor from the system."""
    vendor = db.session.get(Customer, vendor_id)
    if vendor is None:
        abort(404)
    db.session.delete(vendor)
    db.session.commit()
    log_activity(f'Deleted vendor {vendor.id}')
    flash('Vendor deleted successfully!', 'success')
    return redirect(url_for('vendor.view_vendors'))


@glcode_bp.route('/gl_codes')
@login_required
def view_gl_codes():
    """List GL codes."""
    codes = GLCode.query.all()
    return render_template('gl_codes/view_gl_codes.html', codes=codes)


@glcode_bp.route('/gl_codes/create', methods=['GET', 'POST'])
@login_required
def create_gl_code():
    """Create a new GL code."""
    form = GLCodeForm()
    if form.validate_on_submit():
        code = GLCode(code=form.code.data, description=form.description.data)
        db.session.add(code)
        db.session.commit()
        flash('GL Code created successfully!', 'success')
        return redirect(url_for('glcode.view_gl_codes'))
    return render_template('gl_codes/add_gl_code.html', form=form)


@glcode_bp.route('/gl_codes/<int:code_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_gl_code(code_id):
    """Edit an existing GL code."""
    code = db.session.get(GLCode, code_id)
    if code is None:
        abort(404)
    form = GLCodeForm(obj=code)
    if form.validate_on_submit():
        code.code = form.code.data
        code.description = form.description.data
        db.session.commit()
        flash('GL Code updated successfully!', 'success')
        return redirect(url_for('glcode.view_gl_codes'))
    return render_template('gl_codes/edit_gl_code.html', form=form)


@glcode_bp.route('/gl_codes/<int:code_id>/delete', methods=['GET'])
@login_required
def delete_gl_code(code_id):
    """Delete a GL code."""
    code = db.session.get(GLCode, code_id)
    if code is None:
        abort(404)
    db.session.delete(code)
    db.session.commit()
    flash('GL Code deleted successfully!', 'success')
    return redirect(url_for('glcode.view_gl_codes'))


@product.route('/search_products')
def search_products():
    """Return products matching a search query."""
    # Retrieve query parameter from the URL
    query = request.args.get('query', '').lower()
    # Query the database for products that match the search query
    matched_products = Product.query.filter(Product.name.ilike(f'%{query}%')).all()
    # Include id so that search results can be referenced elsewhere
    product_data = [
        {'id': product.id, 'name': product.name, 'price': product.price}
        for product in matched_products
    ]
    # Return matched product names and prices as JSON
    return jsonify(product_data)


@invoice.route('/create_invoice', methods=['GET', 'POST'])
@login_required
def create_invoice():
    """Create a sales invoice."""
    form = InvoiceForm()
    form.customer.choices = [(c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()]

    if form.validate_on_submit():
        customer = db.session.get(Customer, form.customer.data)
        if customer is None:
            abort(404)
        today = datetime.now().strftime('%d%m%y')
        count = Invoice.query.filter(
            func.date(Invoice.date_created) == func.current_date(),
            Invoice.customer_id == customer.id
        ).count() + 1
        invoice_id = f"{customer.first_name[0]}{customer.last_name[0]}{customer.id}{today}{count:02}"

        invoice = Invoice(
            id=invoice_id,
            customer_id=customer.id,
            user_id=current_user.id
        )
        db.session.add(invoice)

        product_data = form.products.data.removesuffix(":").split(':')

        for entry in product_data:
            try:
                product_name, quantity, override_gst, override_pst = entry.split('?')
                product = Product.query.filter_by(name=product_name).first()

                if product:
                    quantity = float(quantity)
                    unit_price = product.price
                    line_subtotal = quantity * unit_price

                    # Parse overrides correctly (can be 0, 1, or empty string)
                    override_gst = None if override_gst == '' else bool(int(override_gst))
                    override_pst = None if override_pst == '' else bool(int(override_pst))

                    # Apply tax rules
                    apply_gst = override_gst if override_gst is not None else not customer.gst_exempt
                    apply_pst = override_pst if override_pst is not None else not customer.pst_exempt

                    line_gst = line_subtotal * 0.05 if apply_gst else 0
                    line_pst = line_subtotal * 0.07 if apply_pst else 0

                    invoice_product = InvoiceProduct(
                        invoice_id=invoice.id,
                        product_id=product.id,
                        quantity=quantity,
                        override_gst=override_gst,
                        override_pst=override_pst,
                        unit_price=unit_price,
                        line_subtotal=line_subtotal,
                        line_gst=line_gst,
                        line_pst=line_pst
                    )
                    db.session.add(invoice_product)

                    # Reduce product inventory
                    product.quantity = (product.quantity or 0) - quantity

                    # Reduce item inventories based on recipe
                    for recipe_item in product.recipe_items:
                        item = recipe_item.item
                        item.quantity = (item.quantity or 0) - (recipe_item.quantity * quantity)
                else:
                    flash(f"Product '{product_name}' not found.", 'danger')

            except ValueError:
                flash(f"Invalid product data format: '{entry}'", 'danger')

        db.session.commit()
        log_activity(f'Created invoice {invoice.id}')
        flash('Invoice created successfully!', 'success')
        return redirect(url_for('invoice.view_invoices'))

    return render_template('invoices/create_invoice.html', form=form)


@invoice.route('/delete_invoice/<invoice_id>', methods=['GET'])
@login_required
def delete_invoice(invoice_id):
    """Delete an invoice and its lines."""
    # Retrieve the invoice object from the database
    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None:
        abort(404)
    # Delete the invoice from the database
    db.session.delete(invoice)
    db.session.commit()
    log_activity(f'Deleted invoice {invoice.id}')
    flash('Invoice deleted successfully!', 'success')
    # Redirect the user to the home page or any other appropriate page
    return redirect(url_for('invoice.view_invoices'))


@invoice.route('/view_invoice/<invoice_id>', methods=['GET'])
@login_required
def view_invoice(invoice_id):
    """Render an invoice for viewing."""
    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None:
        abort(404)

    subtotal = 0
    gst_total = 0
    pst_total = 0

    for invoice_product in invoice.products:
        # Use stored values instead of recalculating from current product price
        line_total = invoice_product.line_subtotal
        subtotal += line_total
        gst_total += invoice_product.line_gst
        pst_total += invoice_product.line_pst

    total = subtotal + gst_total + pst_total

    return render_template(
        'invoices/view_invoice.html',
        invoice=invoice,
        subtotal=subtotal,
        gst=gst_total,
        pst=pst_total,
        total=total,
        GST=GST
    )

@invoice.route('/get_customer_tax_status/<int:customer_id>')
@login_required
def get_customer_tax_status(customer_id):
    """Return GST and PST exemptions for a customer."""
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    return {
        "gst_exempt": customer.gst_exempt,
        "pst_exempt": customer.pst_exempt
    }


@invoice.route('/view_invoices', methods=['GET', 'POST'])
@login_required
def view_invoices():
    """List invoices with optional filters."""
    form = InvoiceFilterForm()
    form.vendor_id.choices = [(-1, 'All')] + [
        (c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()
    ]

    # Determine filter values from form submission or query params
    if form.validate_on_submit():
        invoice_id = form.invoice_id.data
        vendor_id = form.vendor_id.data
        start_date = form.start_date.data
        end_date = form.end_date.data
    else:
        invoice_id = request.args.get('invoice_id', '')
        vendor_id = request.args.get('vendor_id', type=int)
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        start_date = datetime.fromisoformat(start_date_str) if start_date_str else None
        end_date = datetime.fromisoformat(end_date_str) if end_date_str else None
        form.invoice_id.data = invoice_id
        if vendor_id is not None:
            form.vendor_id.data = vendor_id
        if start_date:
            form.start_date.data = start_date
        if end_date:
            form.end_date.data = end_date

    query = Invoice.query
    if invoice_id:
        query = query.filter(Invoice.id.ilike(f"%{invoice_id}%"))
    if vendor_id and vendor_id != -1:
        query = query.filter(Invoice.customer_id == vendor_id)
    if start_date:
        query = query.filter(Invoice.date_created >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(Invoice.date_created <= datetime.combine(end_date, datetime.max.time()))

    invoices = query.order_by(Invoice.date_created.desc()).all()
    return render_template('invoices/view_invoices.html', invoices=invoices, form=form)

@report.route('/reports/vendor-invoices', methods=['GET', 'POST'])
def vendor_invoice_report():
    """Form to select vendor invoice report parameters."""
    form = VendorInvoiceReportForm()
    form.customer.choices = [(c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()]

    if form.validate_on_submit():
        return redirect(url_for(
            'report.vendor_invoice_report_results',
            customer_ids=",".join(str(id) for id in form.customer.data),
            start=form.start_date.data.isoformat(),
            end=form.end_date.data.isoformat()
        ))

    return render_template('report_vendor_invoices.html', form=form)


@report.route('/reports/vendor-invoices/results')
def vendor_invoice_report_results():
    """Show vendor invoice report based on query parameters."""
    customer_ids = request.args.get('customer_ids')
    start = request.args.get('start')
    end = request.args.get('end')

    # Convert comma-separated IDs to list of ints
    id_list = [int(cid) for cid in customer_ids.split(",") if cid.isdigit()]
    customers = Customer.query.filter(Customer.id.in_(id_list)).all()

    invoices = Invoice.query.filter(
        Invoice.customer_id.in_(id_list),
        Invoice.date_created >= start,
        Invoice.date_created <= end
    ).all()

    # Compute totals with proper GST/PST logic
    enriched_invoices = []
    for invoice in invoices:
        subtotal = 0
        gst_total = 0
        pst_total = 0

        for item in invoice.products:
            line_total = item.quantity * item.product.price
            subtotal += line_total

            apply_gst = item.override_gst if item.override_gst is not None else not invoice.customer.gst_exempt
            apply_pst = item.override_pst if item.override_pst is not None else not invoice.customer.pst_exempt

            if apply_gst:
                gst_total += line_total * 0.05
            if apply_pst:
                pst_total += line_total * 0.07

        enriched_invoices.append({
            "invoice": invoice,
            "total": subtotal + gst_total + pst_total
        })

    return render_template(
        'report_vendor_invoice_results.html',
        customers=customers,
        invoices=enriched_invoices,
        start=start,
        end=end
    )

@report.route('/reports/product-sales', methods=['GET', 'POST'])
def product_sales_report():
    """Generate a report on product sales and profit."""
    form = ProductSalesReportForm()
    report_data = []

    if form.validate_on_submit():
        start = form.start_date.data
        end = form.end_date.data

        # Query all relevant InvoiceProduct entries
        products = db.session.query(
    Product.id,
    Product.name,
    Product.cost,
    Product.price,
    db.func.sum(InvoiceProduct.quantity).label('total_quantity')
).join(InvoiceProduct, InvoiceProduct.product_id == Product.id
).join(Invoice, Invoice.id == InvoiceProduct.invoice_id
).filter(
    Invoice.date_created >= start,
    Invoice.date_created <= end
).group_by(Product.id).all()

        # Format the report
        for p in products:
            profit_each = p.price - p.cost
            total_revenue = p.total_quantity * p.price
            total_profit = p.total_quantity * profit_each
            report_data.append({
                'name': p.name,
                'quantity': p.total_quantity,
                'cost': p.cost,
                'price': p.price,
                'profit_each': profit_each,
                'revenue': total_revenue,
                'profit': total_profit
            })

        return render_template('report_product_sales_results.html', form=form, report=report_data)

    return render_template('report_product_sales.html', form=form)


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
                db.session.add(PurchaseInvoiceItem(invoice_id=invoice.id, item_id=item_id, unit_id=unit_id, quantity=quantity, cost=cost))
                item_obj = db.session.get(Item, item_id)
                if item_obj:
                    factor = 1
                    if unit_id:
                        unit = db.session.get(ItemUnit, unit_id)
                        if unit:
                            factor = unit.factor
                    item_obj.quantity = (item_obj.quantity or 0) + quantity * factor
                    # store cost per base unit (always positive)
                    item_obj.cost = abs(cost) / factor if factor else abs(cost)
                    record = LocationStandItem.query.filter_by(location_id=invoice.location_id, item_id=item_id).first()
                    if not record:
                        record = LocationStandItem(location_id=invoice.location_id, item_id=item_id, expected_count=0)
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


@purchase.route('/purchase_invoices/<int:invoice_id>/reverse')
@login_required
def reverse_purchase_invoice(invoice_id):
    """Undo receipt of a purchase invoice."""
    invoice = db.session.get(PurchaseInvoice, invoice_id)
    if invoice is None:
        abort(404)
    po = db.session.get(PurchaseOrder, invoice.purchase_order_id)
    if po is None:
        abort(404)
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
            record.expected_count -= inv_item.quantity * factor
    PurchaseInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
    db.session.delete(invoice)
    po.received = False
    db.session.commit()
    flash('Invoice reversed successfully', 'success')
    return redirect(url_for('purchase.view_purchase_orders'))
