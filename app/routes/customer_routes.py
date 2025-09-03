from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app import db
from app.forms import CustomerForm, DeleteForm
from app.models import Customer
from app.utils.activity import log_activity

customer = Blueprint("customer", __name__)


@customer.route("/customers")
@login_required
def view_customers():
    """Display all customers."""
    customers = Customer.query.filter_by(archived=False).all()
    delete_form = DeleteForm()
    return render_template(
        "customers/view_customers.html",
        customers=customers,
        delete_form=delete_form,
    )


@customer.route("/customers/create", methods=["GET", "POST"])
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
            pst_exempt=not form.pst_exempt.data,
        )
        db.session.add(customer)
        db.session.commit()
        log_activity(f"Created customer {customer.id}")
        flash("Customer created successfully!", "success")
        return redirect(url_for("customer.view_customers"))
    return render_template(
        "customers/customer_form.html", form=form, title="Create Customer"
    )


@customer.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
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
        log_activity(f"Edited customer {customer.id}")
        flash("Customer updated successfully!", "success")
        return redirect(url_for("customer.view_customers"))

    elif request.method == "GET":
        form.first_name.data = customer.first_name
        form.last_name.data = customer.last_name
        # Invert stored values so the checkbox represents charging tax
        form.gst_exempt.data = not customer.gst_exempt
        form.pst_exempt.data = not customer.pst_exempt

    return render_template(
        "customers/customer_form.html", form=form, title="Edit Customer"
    )


@customer.route("/customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def delete_customer(customer_id):
    """Delete a customer."""
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    customer.archived = True
    db.session.commit()
    log_activity(f"Archived customer {customer.id}")
    flash("Customer archived successfully!", "success")
    return redirect(url_for("customer.view_customers"))
