from flask import Blueprint, render_template, flash, redirect, url_for, abort, request
from flask_login import login_required

from app import db
from app.utils.activity import log_activity
from app.forms import CustomerForm
from app.models import Customer

customer = Blueprint('customer', __name__)

@customer.route('/customers')
@login_required
def view_customers():
    """Display all customers."""
    customers = Customer.query.filter_by(archived=False).all()
    return render_template('customers/view_customers.html', customers=customers)


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
    return render_template('customers/create_customer.html', form=form)


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

    return render_template('customers/edit_customer.html', form=form)


@customer.route('/customers/<int:customer_id>/delete', methods=['GET'])
@login_required
def delete_customer(customer_id):
    """Delete a customer."""
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        abort(404)
    customer.archived = True
    db.session.commit()
    log_activity(f'Archived customer {customer.id}')
    flash('Customer archived successfully!', 'success')
    return redirect(url_for('customer.view_customers'))
