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
product = Blueprint('product', __name__)
customer = Blueprint('customer', __name__)
report = Blueprint('report', __name__)
purchase = Blueprint('purchase', __name__)
vendor = Blueprint('vendor', __name__)
glcode_bp = Blueprint('glcode', __name__)




@main.route('/')
@login_required
def home():
    """Render the transfers dashboard."""
    return render_template('transfers/view_transfers.html', user=current_user)








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
