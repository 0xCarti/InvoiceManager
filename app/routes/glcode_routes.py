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

glcode_bp = Blueprint('glcode', __name__)

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
