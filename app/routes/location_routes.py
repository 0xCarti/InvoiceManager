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
from app.forms import DeleteForm, LocationForm
from app.models import Location, LocationStandItem, Product, Transfer
from app.utils.activity import log_activity

location = Blueprint("locations", __name__)


@location.route("/locations/add", methods=["GET", "POST"])
@login_required
def add_location():
    """Create a new location."""
    form = LocationForm()
    if form.validate_on_submit():
        new_location = Location(
            name=form.name.data, is_spoilage=form.is_spoilage.data
        )
        product_ids = (
            [int(pid) for pid in form.products.data.split(",") if pid]
            if form.products.data
            else []
        )
        selected_products = [
            db.session.get(Product, pid) for pid in product_ids
        ]
        new_location.products = selected_products
        db.session.add(new_location)
        db.session.commit()

        # Add stand sheet items for countable recipe items
        for product_obj in selected_products:
            for recipe_item in product_obj.recipe_items:
                if recipe_item.countable:
                    exists = LocationStandItem.query.filter_by(
                        location_id=new_location.id,
                        item_id=recipe_item.item_id,
                    ).first()
                    if not exists:
                        db.session.add(
                            LocationStandItem(
                                location_id=new_location.id,
                                item_id=recipe_item.item_id,
                                expected_count=0,
                                purchase_gl_code_id=recipe_item.item.purchase_gl_code_id,
                            )
                        )
        db.session.commit()
        log_activity(f"Added location {new_location.name}")
        flash("Location added successfully!")
        return redirect(url_for("locations.view_locations"))
    selected_products = []
    if form.products.data:
        ids = [int(pid) for pid in form.products.data.split(",") if pid]
        selected_products = Product.query.filter(Product.id.in_(ids)).all()
    selected_data = [{"id": p.id, "name": p.name} for p in selected_products]
    return render_template(
        "locations/add_location.html",
        form=form,
        selected_products=selected_data,
    )


@location.route("/locations/edit/<int:location_id>", methods=["GET", "POST"])
@login_required
def edit_location(location_id):
    """Edit an existing location."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    form = LocationForm(obj=location)
    if request.method == "GET":
        form.products.data = ",".join(str(p.id) for p in location.products)

    if form.validate_on_submit():
        location.name = form.name.data
        location.is_spoilage = form.is_spoilage.data
        product_ids = (
            [int(pid) for pid in form.products.data.split(",") if pid]
            if form.products.data
            else []
        )
        selected_products = [
            db.session.get(Product, pid) for pid in product_ids
        ]
        location.products = selected_products
        db.session.commit()

        # Ensure stand sheet items exist for new products
        for product_obj in selected_products:
            for recipe_item in product_obj.recipe_items:
                if recipe_item.countable:
                    exists = LocationStandItem.query.filter_by(
                        location_id=location.id, item_id=recipe_item.item_id
                    ).first()
                    if not exists:
                        db.session.add(
                            LocationStandItem(
                                location_id=location.id,
                                item_id=recipe_item.item_id,
                                expected_count=0,
                                purchase_gl_code_id=recipe_item.item.purchase_gl_code_id,
                            )
                        )
        db.session.commit()
        log_activity(f"Edited location {location.id}")
        flash("Location updated successfully.", "success")
        return redirect(
            url_for("locations.edit_location", location_id=location.id)
        )

    # Query for completed transfers to this location
    transfers_to_location = Transfer.query.filter_by(
        to_location_id=location_id, completed=True
    ).all()

    selected_data = [{"id": p.id, "name": p.name} for p in location.products]
    return render_template(
        "locations/edit_location.html",
        form=form,
        location=location,
        transfers=transfers_to_location,
        selected_products=selected_data,
    )


@location.route("/locations/<int:location_id>/stand_sheet")
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
                stand_items.append(
                    {"item": recipe_item.item, "expected": expected}
                )

    return render_template(
        "locations/stand_sheet.html",
        location=location,
        stand_items=stand_items,
    )


@location.route("/locations")
@login_required
def view_locations():
    """List all locations."""
    page = request.args.get("page", 1, type=int)
    locations = (
        Location.query.filter_by(archived=False)
        .order_by(Location.name)
        .paginate(page=page, per_page=20)
    )
    delete_form = DeleteForm()
    return render_template(
        "locations/view_locations.html",
        locations=locations,
        delete_form=delete_form,
    )


@location.route("/locations/delete/<int:location_id>", methods=["POST"])
@login_required
def delete_location(location_id):
    """Remove a location from the database."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    location.archived = True
    db.session.commit()
    log_activity(f"Archived location {location.id}")
    flash("Location archived successfully!")
    return redirect(url_for("locations.view_locations"))
