from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app import db
from app.forms import DeleteForm, LocationForm
from app.models import Location, LocationStandItem, Product
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
        existing_items = {
            item.item_id: item
            for item in LocationStandItem.query.filter_by(
                location_id=new_location.id
            ).all()
        }
        for product_obj in selected_products:
            for recipe_item in product_obj.recipe_items:
                if (
                    recipe_item.countable
                    and recipe_item.item_id not in existing_items
                ):
                    new_item = LocationStandItem(
                        location_id=new_location.id,
                        item_id=recipe_item.item_id,
                        expected_count=0,
                        purchase_gl_code_id=recipe_item.item.purchase_gl_code_id,
                    )
                    db.session.add(new_item)
                    existing_items[recipe_item.item_id] = new_item
        db.session.commit()
        log_activity(f"Added location {new_location.name}")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                {
                    "success": True,
                    "action": "create",
                    "location": {
                        "id": new_location.id,
                        "name": new_location.name,
                    },
                }
            )
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
        existing_items = {
            item.item_id: item
            for item in LocationStandItem.query.filter_by(
                location_id=location.id
            ).all()
        }
        for product_obj in selected_products:
            for recipe_item in product_obj.recipe_items:
                if (
                    recipe_item.countable
                    and recipe_item.item_id not in existing_items
                ):
                    new_item = LocationStandItem(
                        location_id=location.id,
                        item_id=recipe_item.item_id,
                        expected_count=0,
                        purchase_gl_code_id=recipe_item.item.purchase_gl_code_id,
                    )
                    db.session.add(new_item)
                    existing_items[recipe_item.item_id] = new_item
        db.session.commit()
        log_activity(f"Edited location {location.id}")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                {
                    "success": True,
                    "action": "update",
                    "location": {"id": location.id, "name": location.name},
                }
            )
        flash("Location updated successfully.", "success")
        return redirect(
            url_for("locations.edit_location", location_id=location.id)
        )

    selected_data = [{"id": p.id, "name": p.name} for p in location.products]
    return render_template(
        "locations/edit_location.html",
        form=form,
        location=location,
        selected_products=selected_data,
    )


@location.route("/locations/<int:source_id>/copy_items", methods=["POST"])
@login_required
def copy_location_items(source_id: int):
    """Copy products and stand sheet items from one location to others.

    The target location ids can be supplied either as form data or JSON via the
    ``target_ids`` key (list) or a single ``target_id``. Any existing products
    and stand sheet items on the target locations are overwritten to match the
    source exactly.
    """
    source = db.session.get(Location, source_id)
    if source is None:
        abort(404)

    # Gather target ids from either JSON payload or form data
    if request.is_json:
        data = request.get_json(silent=True) or {}
        ids = data.get("target_ids") or (
            [data.get("target_id")] if data.get("target_id") is not None else []
        )
    else:
        ids_str = request.form.get("target_ids") or request.form.get("target_id")
        ids = [s.strip() for s in ids_str.split(",") if s.strip()] if ids_str else []

    if not ids:
        abort(400)

    target_ids = [int(tid) for tid in ids]

    # Cache source products and stand items for reuse
    source_products = list(source.products)
    source_item_counts = {
        item.item_id: item.expected_count
        for item in LocationStandItem.query.filter_by(location_id=source.id).all()
    }

    processed_targets = []
    for tid in target_ids:
        target = db.session.get(Location, tid)
        if target is None:
            abort(404)

        # Overwrite products
        target.products = list(source_products)

        # Remove existing stand sheet items
        LocationStandItem.query.filter_by(location_id=target.id).delete()

        # Recreate stand sheet items matching the source
        for product in source_products:
            for recipe_item in product.recipe_items:
                if recipe_item.countable:
                    expected = source_item_counts.get(recipe_item.item_id, 0)
                    db.session.add(
                        LocationStandItem(
                            location_id=target.id,
                            item_id=recipe_item.item_id,
                            expected_count=expected,
                            purchase_gl_code_id=recipe_item.item.purchase_gl_code_id,
                        )
                    )

        processed_targets.append(str(tid))

    db.session.commit()
    log_activity(
        f"Copied location items from {source.id} to {', '.join(processed_targets)}"
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({"success": True})

    flash("Items copied successfully.", "success")
    return redirect(
        url_for("locations.edit_location", location_id=target_ids[0])
    )


@location.route("/locations/<int:location_id>/stand_sheet")
@login_required
def view_stand_sheet(location_id):
    """Display the expected item counts for a location."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)

    # Preload all stand sheet records for the location to avoid querying for
    # each individual item when building the stand sheet. Mapping the records by
    # ``item_id`` lets us perform fast dictionary lookups inside the loop
    # below.
    stand_records = LocationStandItem.query.filter_by(
        location_id=location_id
    ).all()
    stand_by_item_id = {record.item_id: record for record in stand_records}

    stand_items = []
    seen = set()
    for product_obj in location.products:
        for recipe_item in product_obj.recipe_items:
            if recipe_item.countable and recipe_item.item_id not in seen:
                seen.add(recipe_item.item_id)
                record = stand_by_item_id.get(recipe_item.item_id)
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
    name_query = request.args.get("name_query", "")
    match_mode = request.args.get("match_mode", "contains")
    archived = request.args.get("archived", "active")

    query = Location.query
    if archived == "active":
        query = query.filter(Location.archived.is_(False))
    elif archived == "archived":
        query = query.filter(Location.archived.is_(True))

    if name_query:
        if match_mode == "exact":
            query = query.filter(Location.name == name_query)
        elif match_mode == "startswith":
            query = query.filter(Location.name.like(f"{name_query}%"))
        elif match_mode == "not_contains":
            query = query.filter(Location.name.notlike(f"%{name_query}%"))
        else:
            query = query.filter(Location.name.like(f"%{name_query}%"))

    locations = query.order_by(Location.name).paginate(page=page, per_page=20)
    delete_form = DeleteForm()
    return render_template(
        "locations/view_locations.html",
        locations=locations,
        delete_form=delete_form,
        name_query=name_query,
        match_mode=match_mode,
        archived=archived,
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
