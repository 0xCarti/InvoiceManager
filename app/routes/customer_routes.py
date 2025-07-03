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
from app.forms import VendorInvoiceReportForm, ProductSalesReportForm

customer = Blueprint('customer', __name__)

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
            # Checkbox checked means charge tax, so exemption is the inverse
            gst_exempt=not form.gst_exempt.data,
            pst_exempt=not form.pst_exempt.data
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
        # Store exemptions as the inverse of the checkbox state
        customer.gst_exempt = not form.gst_exempt.data
        customer.pst_exempt = not form.pst_exempt.data
        db.session.commit()
        log_activity(f'Edited customer {customer.id}')
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('customer.view_customers'))

    elif request.method == 'GET':
        form.first_name.data = customer.first_name
        form.last_name.data = customer.last_name
        # Invert stored values so the checkbox represents charging tax
        form.gst_exempt.data = not customer.gst_exempt
        form.pst_exempt.data = not customer.pst_exempt

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
