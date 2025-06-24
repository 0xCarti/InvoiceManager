import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
from app import db, socketio, GST
from app.forms import LocationForm, ItemForm, TransferForm, ImportItemsForm, DateRangeForm, CustomerForm, ProductForm, InvoiceForm, SignupForm, LoginForm
from app.models import Location, Item, Transfer, TransferItem, Customer, Product, Invoice, InvoiceProduct
from datetime import datetime
from flask import Blueprint, render_template
from app.forms import VendorInvoiceReportForm, ProductSalesReportForm
from app.models import Customer, Invoice
from app import db
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


@main.route('/')
@login_required
def home():
    return render_template('transfers/view_transfers.html', user=current_user)


@location.route('/locations/add', methods=['GET', 'POST'])
@login_required
def add_location():
    form = LocationForm()
    if form.validate_on_submit():
        new_location = Location(name=form.name.data)
        db.session.add(new_location)
        db.session.commit()
        flash('Location added successfully!')
        return redirect(url_for('locations.view_locations'))
    return render_template('locations/add_location.html', form=form)


@location.route('/locations/edit/<int:location_id>', methods=['GET', 'POST'])
@login_required
def edit_location(location_id):
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    form = LocationForm(obj=location)

    if form.validate_on_submit():
        form.populate_obj(location)
        db.session.commit()
        flash('Location updated successfully.', 'success')
        return redirect(url_for('location.edit_location', location_id=location.id))

    # Query for completed transfers to this location
    transfers_to_location = Transfer.query.filter_by(to_location_id=location_id, completed=True).all()

    return render_template('locations/edit_location.html', form=form, location=location,
                           transfers=transfers_to_location)


@location.route('/locations')
@login_required
def view_locations():
    locations = Location.query.all()
    return render_template('locations/view_locations.html', locations=locations)


@location.route('/locations/delete/<int:location_id>', methods=['POST'])
@login_required
def delete_location(location_id):
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    db.session.delete(location)
    db.session.commit()
    flash('Location deleted successfully!')
    return redirect(url_for('locations.view_locations'))


@item.route('/items')
@login_required
def view_items():
    items = Item.query.all()
    form = ItemForm()
    return render_template('items/view_items.html', items=items, form=form)


@item.route('/items/add', methods=['GET', 'POST'])
@login_required
def add_item():
    form = ItemForm()
    if form.validate_on_submit():
        item = Item(name=form.name.data)
        db.session.add(item)
        db.session.commit()
        flash('Item added successfully!')
        return redirect(url_for('item.view_items'))
    return render_template('items/add_item.html', form=form)


@item.route('/items/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    form = ItemForm(obj=item)
    if form.validate_on_submit():
        item.name = form.name.data
        db.session.commit()
        flash('Item updated successfully!')
        return redirect(url_for('item.view_items'))
    return render_template('items/edit_item.html', form=form, item=item)


@item.route('/items/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash('Item deleted successfully!')
    return redirect(url_for('item.view_items'))


@item.route('/items/bulk_delete', methods=['POST'])
@login_required
def bulk_delete_items():
    item_ids = request.form.getlist('item_ids')
    if item_ids:
        Item.query.filter(Item.id.in_(item_ids)).delete(synchronize_session='fetch')
        db.session.commit()
        flash('Selected items have been deleted.', 'success')
    else:
        flash('No items selected.', 'warning')
    return redirect(url_for('item.view_items'))


@transfer.route('/transfers', methods=['GET'])
@login_required
def view_transfers():
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
            quantity = request.form.get(f'items-{index}-quantity', type=int)
            if item_id:
                item = db.session.get(Item, item_id)
                if item and quantity:
                    transfer_item = TransferItem(
                        transfer_id=transfer.id,
                        item_id=item.id,
                        quantity=quantity
                    )
                    db.session.add(transfer_item)
        db.session.commit()

        socketio.emit('new_transfer', {'message': 'New transfer added'})

        flash('Transfer added successfully!', 'success')
        return redirect(url_for('transfer.view_transfers'))
    elif form.errors:
        flash('There was an error submitting the transfer.', 'error')

    return render_template('transfers/add_transfer.html', form=form)


@transfer.route('/transfers/edit/<int:transfer_id>', methods=['GET', 'POST'])
@login_required
def edit_transfer(transfer_id):
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
            quantity = request.form.get(f'items-{index}-quantity', type=int)
            if item_id and quantity:  # Ensure both are provided and valid
                new_transfer_item = TransferItem(
                    transfer_id=transfer.id,
                    item_id=int(item_id),
                    quantity=quantity
                )
                db.session.add(new_transfer_item)

        db.session.commit()
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
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    db.session.delete(transfer)
    db.session.commit()
    flash('Transfer deleted successfully!', 'success')
    return redirect(url_for('transfer.view_transfers'))


@transfer.route('/transfers/complete/<int:transfer_id>', methods=['GET'])
@login_required
def complete_transfer(transfer_id):
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    transfer.completed = True
    db.session.commit()
    flash('Transfer marked as complete!', 'success')
    return redirect(url_for('transfer.view_transfers'))


@transfer.route('/transfers/uncomplete/<int:transfer_id>', methods=['GET'])
@login_required
def uncomplete_transfer(transfer_id):
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    transfer.completed = False
    db.session.commit()
    flash('Transfer marked as not completed.', 'success')
    return redirect(url_for('transfer.view_transfers'))


@transfer.route('/transfers/view/<int:transfer_id>', methods=['GET'])
@login_required
def view_transfer(transfer_id):
    transfer = db.session.get(Transfer, transfer_id)
    if transfer is None:
        abort(404)
    transfer_items = TransferItem.query.filter_by(transfer_id=transfer.id).all()
    return render_template('transfers/view_transfer.html', transfer=transfer, transfer_items=transfer_items)


@item.route('/items/search', methods=['GET'])
@login_required
def search_items():
    search_term = request.args.get('term', '')
    items = Item.query.filter(Item.name.ilike(f'%{search_term}%')).all()
    items_data = [{'id': item.id, 'name': item.name} for item in items]  # Create a list of dicts
    return jsonify(items_data)


@item.route('/import_items', methods=['GET', 'POST'])
@login_required
def import_items():
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

        flash('Items imported successfully.', 'success')
        return redirect(url_for('item.import_items'))

    return render_template('items/import_items.html', form=form)


@transfer.route('/transfers/generate_report', methods=['GET', 'POST'])
def generate_report():
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
    aggregated_transfers = session.get('aggregated_transfers', [])
    return render_template('transfers/view_report.html', aggregated_transfers=aggregated_transfers)


@product.route('/products')
@login_required
def view_products():
    products = Product.query.all()
    return render_template('view_products.html', products=products)


@product.route('/products/create', methods=['GET', 'POST'])
@login_required
def create_product():
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(
            name=form.name.data,
            price=form.price.data,
            cost=form.cost.data  # 👈 Save cost
        )
        db.session.add(product)
        db.session.commit()
        flash('Product created successfully!', 'success')
        return redirect(url_for('product.view_products'))
    return render_template('create_product.html', form=form)


@product.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    form = ProductForm()
    if form.validate_on_submit():
        product.name = form.name.data
        product.price = form.price.data
        product.cost = form.cost.data or 0.0  # 👈 Update cost
        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('product.view_products'))
    elif request.method == 'GET':
        form.name.data = product.name
        form.price.data = product.price
        form.cost.data = product.cost or 0.0  # 👈 Pre-fill cost
    else:
        print(form.errors)
        print(form.cost.data)
    return render_template('edit_product.html', form=form)


@product.route('/products/<int:product_id>/delete', methods=['GET'])
@login_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('product.view_products'))


@customer.route('/customers')
@login_required
def view_customers():
    customers = Customer.query.all()
    return render_template('view_customers.html', customers=customers)


@customer.route('/customers/create', methods=['GET', 'POST'])
@login_required
def create_customer():
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
        flash('Customer created successfully!', 'success')
        return redirect(url_for('customer.view_customers'))
    return render_template('create_customer.html', form=form)


@customer.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
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
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted successfully!', 'success')
    return redirect(url_for('customer.view_customers'))


@product.route('/search_products')
def search_products():
    # Retrieve query parameter from the URL
    query = request.args.get('query', '').lower()
    # Query the database for products that match the search query
    matched_products = Product.query.filter(Product.name.ilike(f'%{query}%')).all()
    # Create a list of dictionaries containing product names and prices
    product_data = [{'name': product.name, 'price': product.price} for product in matched_products]
    # Return matched product names and prices as JSON
    return jsonify(product_data)


@invoice.route('/create_invoice', methods=['GET', 'POST'])
@login_required
def create_invoice():
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
                else:
                    flash(f"Product '{product_name}' not found.", 'danger')

            except ValueError:
                flash(f"Invalid product data format: '{entry}'", 'danger')

        db.session.commit()
        flash('Invoice created successfully!', 'success')
        return redirect(url_for('invoice.view_invoices'))

    return render_template('create_invoice.html', form=form)


@invoice.route('/delete_invoice/<invoice_id>', methods=['GET'])
@login_required
def delete_invoice(invoice_id):
    # Retrieve the invoice object from the database
    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None:
        abort(404)
    # Delete the invoice from the database
    db.session.delete(invoice)
    db.session.commit()
    flash('Invoice deleted successfully!', 'success')
    # Redirect the user to the home page or any other appropriate page
    return redirect(url_for('invoice.view_invoices'))


@invoice.route('/view_invoice/<invoice_id>', methods=['GET'])
@login_required
def view_invoice(invoice_id):
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
        'view_invoice.html',
        invoice=invoice,
        subtotal=subtotal,
        gst=gst_total,
        pst=pst_total,
        total=total,
        GST='104805510'  # Replace with your real GST number
    )

@invoice.route('/get_customer_tax_status/<int:customer_id>')
@login_required
def get_customer_tax_status(customer_id):
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    return {
        "gst_exempt": customer.gst_exempt,
        "pst_exempt": customer.pst_exempt
    }


@invoice.route('/view_invoices', methods=['GET'])
@login_required
def view_invoices():
    invoices = Invoice.query.all()
    return render_template('view_invoices.html', invoices=invoices[::-1])

@report.route('/reports/vendor-invoices', methods=['GET', 'POST'])
def vendor_invoice_report():
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
