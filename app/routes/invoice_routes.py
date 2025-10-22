from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app import GST, db
from app.forms import DeleteForm, InvoiceFilterForm, InvoiceForm
from app.models import Customer, Invoice, InvoiceProduct, Product
from app.utils.activity import log_activity
from app.utils.numeric import coerce_float
from app.utils.pagination import build_pagination_args, get_per_page

invoice = Blueprint("invoice", __name__)


def _create_invoice_from_form(form):
    customer = db.session.get(Customer, form.customer.data)
    if customer is None:
        abort(404)
    today = datetime.now().strftime("%d%m%y")
    count = (
        Invoice.query.filter(
            func.date(Invoice.date_created) == func.current_date(),
            Invoice.customer_id == customer.id,
        ).count()
        + 1
    )
    invoice_id = f"{customer.first_name[0]}{customer.last_name[0]}{customer.id}{today}{count:02}"

    invoice = Invoice(
        id=invoice_id, customer_id=customer.id, user_id=current_user.id
    )
    db.session.add(invoice)

    product_data = form.products.data.removesuffix(":").split(":")

    parsed_entries = []
    product_names = set()
    for entry in product_data:
        try:
            product_name, quantity, override_gst, override_pst = entry.split(
                "?"
            )
        except ValueError:
            flash(f"Invalid product data format: '{entry}'", "danger")
            continue
        parsed_entries.append(
            (product_name, quantity, override_gst, override_pst)
        )
        product_names.add(product_name)

    products = (
        Product.query.filter(Product.name.in_(product_names)).all()
        if product_names
        else []
    )
    product_lookup = {p.name: p for p in products}

    for product_name, quantity, override_gst, override_pst in parsed_entries:
        product = product_lookup.get(product_name)

        if product:
            quantity_value = coerce_float(quantity)
            if quantity_value is None:
                continue
            quantity = quantity_value
            unit_price = product.price
            line_subtotal = quantity * unit_price

            override_gst = (
                None if override_gst == "" else bool(int(override_gst))
            )
            override_pst = (
                None if override_pst == "" else bool(int(override_pst))
            )

            apply_gst = (
                override_gst
                if override_gst is not None
                else not customer.gst_exempt
            )
            apply_pst = (
                override_pst
                if override_pst is not None
                else not customer.pst_exempt
            )

            line_gst = line_subtotal * 0.05 if apply_gst else 0
            line_pst = line_subtotal * 0.07 if apply_pst else 0

            invoice_product = InvoiceProduct(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=quantity,
                override_gst=override_gst,
                override_pst=override_pst,
                unit_price=unit_price,
                line_subtotal=line_subtotal,
                line_gst=line_gst,
                line_pst=line_pst,
            )
            db.session.add(invoice_product)

            product.quantity = (product.quantity or 0) - quantity

            for recipe_item in product.recipe_items:
                item = recipe_item.item
                factor = recipe_item.unit.factor if recipe_item.unit else 1
                item.quantity = (item.quantity or 0) - (
                    recipe_item.quantity * factor * quantity
                )

    db.session.commit()
    log_activity(f"Created invoice {invoice.id}")
    return invoice


@invoice.route("/create_invoice", methods=["GET", "POST"])
@login_required
def create_invoice():
    """Create a sales invoice."""
    form = InvoiceForm()
    form.customer.choices = [
        (c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()
    ]

    if form.validate_on_submit():
        _create_invoice_from_form(form)
        flash("Invoice created successfully!", "success")
        return redirect(url_for("invoice.view_invoices"))

    return render_template("invoices/create_invoice.html", form=form)


@invoice.route("/delete_invoice/<invoice_id>", methods=["POST"])
@login_required
def delete_invoice(invoice_id):
    """Delete an invoice and its lines."""
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    # Retrieve the invoice object from the database
    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None:
        abort(404)
    # Delete the invoice from the database
    db.session.delete(invoice)
    db.session.commit()
    log_activity(f"Deleted invoice {invoice.id}")
    flash("Invoice deleted successfully!", "success")
    # Redirect the user to the home page or any other appropriate page
    return redirect(url_for("invoice.view_invoices"))


@invoice.route("/view_invoice/<invoice_id>", methods=["GET"])
@login_required
def view_invoice(invoice_id):
    """Render an invoice for viewing."""
    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None:
        abort(404)

    subtotal = 0
    gst_total = 0
    pst_total = 0

    invoice_lines = []
    for invoice_product in invoice.products:
        # Use stored values instead of recalculating from current product price
        line_total = invoice_product.line_subtotal
        subtotal += line_total
        gst_total += invoice_product.line_gst
        pst_total += invoice_product.line_pst
        name = (
            invoice_product.product.name
            if invoice_product.product
            else invoice_product.product_name
        )
        invoice_lines.append((invoice_product, name))

    total = subtotal + gst_total + pst_total

    return render_template(
        "invoices/view_invoice.html",
        invoice=invoice,
        invoice_lines=invoice_lines,
        subtotal=subtotal,
        gst=gst_total,
        pst=pst_total,
        total=total,
        GST=GST,
        retail_pop_price=current_app.config.get("RETAIL_POP_PRICE", "0.00"),
    )


@invoice.route("/get_customer_tax_status/<int:customer_id>")
@login_required
def get_customer_tax_status(customer_id):
    """Return GST and PST exemptions for a customer."""
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    return {
        "gst_exempt": customer.gst_exempt,
        "pst_exempt": customer.pst_exempt,
    }


@invoice.route("/api/filter_invoices")
@login_required
def filter_invoices_api():
    """Return invoices matching filters as JSON."""
    invoice_id = request.args.get("invoice_id", "")
    customer_id = request.args.get("customer_id", type=int)
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    start_date = (
        datetime.fromisoformat(start_date_str) if start_date_str else None
    )
    end_date = datetime.fromisoformat(end_date_str) if end_date_str else None

    query = Invoice.query
    if invoice_id:
        query = query.filter(Invoice.id.ilike(f"%{invoice_id}%"))
    if customer_id and customer_id != -1:
        query = query.filter(Invoice.customer_id == customer_id)
    if start_date:
        query = query.filter(
            Invoice.date_created
            >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        query = query.filter(
            Invoice.date_created
            <= datetime.combine(end_date, datetime.max.time())
        )

    invoices = query.order_by(Invoice.date_created.desc()).all()
    data = [
        {
            "id": inv.id,
            "date": inv.date_created.strftime("%Y-%m-%d"),
            "customer": f"{inv.customer.first_name} {inv.customer.last_name}",
        }
        for inv in invoices
    ]
    return {"invoices": data}


@invoice.route("/api/create_invoice", methods=["POST"])
@login_required
def create_invoice_api():
    """Create an invoice via AJAX and return JSON."""
    form = InvoiceForm()
    form.customer.choices = [
        (c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()
    ]
    if form.validate_on_submit():
        invoice = _create_invoice_from_form(form)
        customer = invoice.customer
        return {
            "invoice": {
                "id": invoice.id,
                "date": invoice.date_created.strftime("%Y-%m-%d"),
                "customer": f"{customer.first_name} {customer.last_name}",
            }
        }
    return {"errors": form.errors}, 400


@invoice.route("/view_invoices", methods=["GET", "POST"])
@login_required
def view_invoices():
    """List invoices with optional filters."""
    form = InvoiceFilterForm()
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    form.customer_id.choices = [(-1, "All")] + [
        (c.id, f"{c.first_name} {c.last_name}")
        for c in Customer.query.paginate(
            page=page, per_page=per_page
        ).items
    ]

    # Determine filter values from form submission or query params
    if form.validate_on_submit():
        invoice_id = form.invoice_id.data
        customer_id = form.customer_id.data
        start_date = form.start_date.data
        end_date = form.end_date.data
    else:
        invoice_id = request.args.get("invoice_id", "")
        customer_id = request.args.get("customer_id", type=int)
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        start_date = (
            datetime.fromisoformat(start_date_str) if start_date_str else None
        )
        end_date = (
            datetime.fromisoformat(end_date_str) if end_date_str else None
        )
        form.invoice_id.data = invoice_id
        if customer_id is not None:
            form.customer_id.data = customer_id
        if start_date:
            form.start_date.data = start_date
        if end_date:
            form.end_date.data = end_date

    query = Invoice.query
    if invoice_id:
        query = query.filter(Invoice.id.ilike(f"%{invoice_id}%"))
    if customer_id and customer_id != -1:
        query = query.filter(Invoice.customer_id == customer_id)
    if start_date:
        query = query.filter(
            Invoice.date_created
            >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        query = query.filter(
            Invoice.date_created
            <= datetime.combine(end_date, datetime.max.time())
        )
    invoices = query.order_by(Invoice.date_created.desc()).paginate(
        page=page, per_page=per_page
    )
    delete_form = DeleteForm()
    create_form = InvoiceForm()
    create_form.customer.choices = [
        (c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()
    ]
    return render_template(
        "invoices/view_invoices.html",
        invoices=invoices,
        form=form,
        delete_form=delete_form,
        create_form=create_form,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
    )
