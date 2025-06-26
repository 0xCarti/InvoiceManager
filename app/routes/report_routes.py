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

report = Blueprint('report', __name__)

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

