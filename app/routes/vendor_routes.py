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

vendor = Blueprint('vendor', __name__)

@vendor.route('/vendors')
@login_required
def view_vendors():
    """Display all vendors."""
    vendors = Vendor.query.all()
    return render_template('view_vendors.html', vendors=vendors)


@vendor.route('/vendors/create', methods=['GET', 'POST'])
@login_required
def create_vendor():
    """Create a new vendor."""
    form = CustomerForm()
    if form.validate_on_submit():
        vendor = Vendor(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            # Checkbox checked means charge tax, so exemption is the inverse
            gst_exempt=not form.gst_exempt.data,
            pst_exempt=not form.pst_exempt.data
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
    vendor = db.session.get(Vendor, vendor_id)
    if vendor is None:
        abort(404)
    form = CustomerForm()

    if form.validate_on_submit():
        vendor.first_name = form.first_name.data
        vendor.last_name = form.last_name.data
        # Store exemptions as the inverse of the checkbox state
        vendor.gst_exempt = not form.gst_exempt.data
        vendor.pst_exempt = not form.pst_exempt.data
        db.session.commit()
        log_activity(f'Edited vendor {vendor.id}')
        flash('Vendor updated successfully!', 'success')
        return redirect(url_for('vendor.view_vendors'))

    elif request.method == 'GET':
        form.first_name.data = vendor.first_name
        form.last_name.data = vendor.last_name
        # Invert stored values so the checkbox represents charging tax
        form.gst_exempt.data = not vendor.gst_exempt
        form.pst_exempt.data = not vendor.pst_exempt

    return render_template('edit_vendor.html', form=form)


@vendor.route('/vendors/<int:vendor_id>/delete', methods=['GET'])
@login_required
def delete_vendor(vendor_id):
    """Remove a vendor from the system."""
    vendor = db.session.get(Vendor, vendor_id)
    if vendor is None:
        abort(404)
    db.session.delete(vendor)
    db.session.commit()
    log_activity(f'Deleted vendor {vendor.id}')
    flash('Vendor deleted successfully!', 'success')
    return redirect(url_for('vendor.view_vendors'))
