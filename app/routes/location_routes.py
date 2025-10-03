from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app import db
from sqlalchemy.orm import selectinload

from app.forms import (
    CSRFOnlyForm,
    DeleteForm,
    ItemForm,
    LocationForm,
    LocationItemAddForm,
)
from app.models import GLCode, Item, Location, LocationStandItem, Menu
from app.utils.activity import log_activity
from app.utils.menu_assignments import apply_menu_products, set_location_menu
from app.utils.pagination import build_pagination_args, get_per_page
from app.utils.units import (
    DEFAULT_BASE_UNIT_CONVERSIONS,
    convert_quantity_for_reporting,
    get_unit_label,
)

location = Blueprint("locations", __name__)


def _protected_location_item_ids(location_obj: Location) -> set[int]:
    """Return item ids that cannot be removed from the location."""

    protected = set()
    for product_obj in location_obj.products:
        for recipe_item in product_obj.recipe_items:
            if recipe_item.countable:
                protected.add(recipe_item.item_id)
    return protected


def _location_items_redirect(location_id: int, page: str | None, per_page: str | None):
    """Redirect back to the location items view preserving pagination."""

    args = {"location_id": location_id}
    if page and page.isdigit():
        args["page"] = int(page)
    if per_page and per_page.isdigit():
        args["per_page"] = int(per_page)
    return redirect(url_for("locations.location_items", **args))
@location.route("/locations/add", methods=["GET", "POST"])
@login_required
def add_location():
    """Create a new location."""
    form = LocationForm()
    if form.validate_on_submit():
        menu_obj = None
        menu_id = form.menu_id.data or 0
        if menu_id:
            menu_obj = db.session.get(Menu, menu_id)
            if menu_obj is None:
                form.menu_id.errors.append("Selected menu is no longer available.")
                return render_template("locations/add_location.html", form=form)
        new_location = Location(
            name=form.name.data, is_spoilage=form.is_spoilage.data
        )
        db.session.add(new_location)
        db.session.flush()
        if menu_obj is not None:
            set_location_menu(new_location, menu_obj)
        else:
            apply_menu_products(new_location, None)
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
                        "menu_name": new_location.current_menu.name
                        if new_location.current_menu
                        else None,
                    },
                }
            )
        flash("Location added successfully!")
        return redirect(url_for("locations.view_locations"))
    if request.method == "GET" and form.menu_id.data is None:
        form.menu_id.data = 0
    return render_template("locations/add_location.html", form=form)


@location.route("/locations/edit/<int:location_id>", methods=["GET", "POST"])
@login_required
def edit_location(location_id):
    """Edit an existing location."""
    location = db.session.get(Location, location_id)
    if location is None:
        abort(404)
    form = LocationForm(obj=location)
    if request.method == "GET":
        form.menu_id.data = location.current_menu_id or 0

    if form.validate_on_submit():
        menu_obj = None
        menu_id = form.menu_id.data or 0
        if menu_id:
            menu_obj = db.session.get(Menu, menu_id)
            if menu_obj is None:
                form.menu_id.errors.append("Selected menu is no longer available.")
                return render_template("locations/edit_location.html", form=form, location=location)
        location.name = form.name.data
        location.is_spoilage = form.is_spoilage.data
        if menu_obj is not None:
            set_location_menu(location, menu_obj)
        elif location.current_menu is not None:
            set_location_menu(location, None)
        db.session.commit()
        log_activity(f"Edited location {location.id}")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                {
                    "success": True,
                    "action": "update",
                    "location": {"id": location.id, "name": location.name, "menu_name": location.current_menu.name if location.current_menu else None},
                }
            )
        flash("Location updated successfully.", "success")
        return redirect(
            url_for("locations.edit_location", location_id=location.id)
        )

    if form.menu_id.data is None:
        form.menu_id.data = location.current_menu_id or 0
    return render_template(
        "locations/edit_location.html",
        form=form,
        location=location,
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
    source_stand_items = {
        record.item_id: record
        for record in LocationStandItem.query.filter_by(location_id=source.id).all()
    }

    processed_targets = []
    for tid in target_ids:
        target = db.session.get(Location, tid)
        if target is None:
            abort(404)

        if source.current_menu is not None:
            set_location_menu(target, source.current_menu)
            db.session.flush()
            for record in list(target.stand_items):
                source_record = source_stand_items.get(record.item_id)
                if source_record is not None:
                    record.expected_count = source_record.expected_count
                    record.purchase_gl_code_id = source_record.purchase_gl_code_id
        else:
            set_location_menu(target, None)
            db.session.flush()
            target.products = list(source_products)
            existing_items: set[int] = set()
            for product in source_products:
                for recipe_item in product.recipe_items:
                    if not recipe_item.countable:
                        continue
                    item_id = recipe_item.item_id
                    if item_id in existing_items:
                        continue
                    source_record = source_stand_items.get(item_id)
                    expected = (
                        source_record.expected_count
                        if source_record is not None
                        else 0
                    )
                    purchase_gl_code_id = (
                        source_record.purchase_gl_code_id
                        if source_record is not None
                        else recipe_item.item.purchase_gl_code_id
                    )
                    db.session.add(
                        LocationStandItem(
                            location=target,
                            item_id=item_id,
                            expected_count=expected,
                            purchase_gl_code_id=purchase_gl_code_id,
                        )
                    )
                    existing_items.add(item_id)

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
    configured = current_app.config.get("BASE_UNIT_CONVERSIONS") or {}
    conversions = dict(DEFAULT_BASE_UNIT_CONVERSIONS)
    conversions.update(configured)

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
                item_obj = recipe_item.item
                if item_obj.base_unit:
                    display_expected, report_unit = convert_quantity_for_reporting(
                        float(expected), item_obj.base_unit, conversions
                    )
                else:
                    display_expected, report_unit = expected, item_obj.base_unit
                stand_items.append(
                    {
                        "item": item_obj,
                        "expected": display_expected,
                        "report_unit_label": get_unit_label(report_unit),
                    }
                )

    return render_template(
        "locations/stand_sheet.html",
        location=location,
        stand_items=stand_items,
    )


@location.route("/locations/<int:location_id>/items", methods=["GET", "POST"])
@login_required
def location_items(location_id):
    """Manage stand sheet items and GL overrides for a location."""
    location_obj = (
        Location.query.options(
            selectinload(Location.stand_items)
            .selectinload(LocationStandItem.item),
            selectinload(Location.stand_items)
            .selectinload(LocationStandItem.purchase_gl_code),
        )
        .filter_by(id=location_id)
        .first()
    )
    if location_obj is None:
        abort(404)

    # Ensure that every countable item from assigned products has a corresponding
    # ``LocationStandItem`` record so it can be displayed and managed on this
    # page. Older data may predate the automatic creation that now happens when
    # editing locations, which meant the management view could appear empty even
    # though the stand sheets contained items. Matching the stand sheet behavior
    # keeps the two views consistent.
    existing_items = {
        record.item_id: record for record in location_obj.stand_items
    }
    created = False
    for product_obj in location_obj.products:
        for recipe_item in product_obj.recipe_items:
            if not recipe_item.countable:
                continue
            if recipe_item.item_id in existing_items:
                continue
            new_record = LocationStandItem(
                location_id=location_id,
                item_id=recipe_item.item_id,
                expected_count=0,
                purchase_gl_code_id=recipe_item.item.purchase_gl_code_id,
            )
            db.session.add(new_record)
            existing_items[recipe_item.item_id] = new_record
            created = True
    if created:
        db.session.commit()

    protected_item_ids = _protected_location_item_ids(location_obj)
    form = CSRFOnlyForm()
    add_form = LocationItemAddForm()
    delete_form = DeleteForm()
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()

    available_choices = [
        (item.id, item.name)
        for item in Item.query.filter_by(archived=False)
        .order_by(Item.name)
        .all()
        if item.id not in existing_items
    ]
    add_form.item_id.choices = available_choices

    query = (
        LocationStandItem.query.join(Item)
        .outerjoin(GLCode, LocationStandItem.purchase_gl_code_id == GLCode.id)
        .options(
            selectinload(LocationStandItem.item),
            selectinload(LocationStandItem.purchase_gl_code),
        )
        .filter(LocationStandItem.location_id == location_id)
        .order_by(Item.name)
    )

    if form.validate_on_submit():
        updated = 0
        for record in query.paginate(page=page, per_page=per_page).items:
            field_name = f"location_gl_code_{record.item_id}"
            raw_value = request.form.get(field_name, "").strip()
            if raw_value:
                try:
                    new_value = int(raw_value)
                except ValueError:
                    continue
            else:
                new_value = None
            current_value = record.purchase_gl_code_id or None
            if new_value != current_value:
                record.purchase_gl_code_id = new_value
                updated += 1
        if updated:
            db.session.commit()
            flash("Item GL codes updated successfully.", "success")
        else:
            flash("No changes were made to item GL codes.", "info")
        return redirect(
            url_for(
                "locations.location_items",
                location_id=location_id,
                page=page,
                per_page=per_page,
            )
        )

    entries = query.paginate(page=page, per_page=per_page)
    for record in entries.items:
        record.is_protected = record.item_id in protected_item_ids
    total_expected = (
        db.session.query(db.func.sum(LocationStandItem.expected_count))
        .filter_by(location_id=location_id)
        .scalar()
        or 0
    )
    return render_template(
        "locations/location_items.html",
        location=location_obj,
        entries=entries,
        total=total_expected,
        per_page=per_page,
        form=form,
        add_form=add_form,
        delete_form=delete_form,
        can_add_items=bool(available_choices),
        purchase_gl_codes=ItemForm._fetch_purchase_gl_codes(),
        pagination_args=build_pagination_args(per_page),
    )


@location.route("/locations/<int:location_id>/items/add", methods=["POST"])
@login_required
def add_location_item(location_id: int):
    """Add a standalone item to a location's stand sheet."""

    location_obj = (
        Location.query.options(selectinload(Location.stand_items))
        .filter_by(id=location_id)
        .first()
    )
    if location_obj is None:
        abort(404)

    add_form = LocationItemAddForm()
    page = request.form.get("page")
    per_page = request.form.get("per_page")

    existing_item_ids = {
        record.item_id for record in location_obj.stand_items
    }
    available_choices = [
        (item.id, item.name)
        for item in Item.query.filter_by(archived=False)
        .order_by(Item.name)
        .all()
        if item.id not in existing_item_ids
    ]
    add_form.item_id.choices = available_choices

    if not available_choices:
        flash("There are no additional items available to add.", "info")
        return _location_items_redirect(location_id, page, per_page)

    if not add_form.validate_on_submit():
        flash("Unable to add item to the location.", "error")
        return _location_items_redirect(location_id, page, per_page)

    item_id = add_form.item_id.data
    if item_id in existing_item_ids:
        flash("This item is already tracked at the location.", "info")
        return _location_items_redirect(location_id, page, per_page)

    item = db.session.get(Item, item_id)
    if item is None or item.archived:
        flash("Selected item is no longer available.", "error")
        return _location_items_redirect(location_id, page, per_page)

    expected = add_form.expected_count.data or 0
    item_name = item.name
    new_record = LocationStandItem(
        location_id=location_id,
        item_id=item_id,
        expected_count=float(expected),
        purchase_gl_code_id=item.purchase_gl_code_id,
    )
    db.session.add(new_record)
    db.session.commit()
    log_activity(
        f"Added item {item_name} to location {location_obj.name}"
    )
    flash("Item added to location.", "success")
    return _location_items_redirect(location_id, page, per_page)


@location.route(
    "/locations/<int:location_id>/items/<int:item_id>/delete",
    methods=["POST"],
)
@login_required
def delete_location_item(location_id: int, item_id: int):
    """Remove a removable item from a location's stand sheet."""

    location_obj = (
        Location.query.options(selectinload(Location.products))
        .filter_by(id=location_id)
        .first()
    )
    if location_obj is None:
        abort(404)

    form = DeleteForm()
    page = request.form.get("page")
    per_page = request.form.get("per_page")
    if not form.validate_on_submit():
        flash("Unable to remove the item from the location.", "error")
        return _location_items_redirect(location_id, page, per_page)

    record = LocationStandItem.query.filter_by(
        location_id=location_id, item_id=item_id
    ).first()
    if record is None:
        flash("Item not found on location.", "error")
        return _location_items_redirect(location_id, page, per_page)

    protected_item_ids = _protected_location_item_ids(location_obj)
    if item_id in protected_item_ids:
        flash(
            "This item is required by a product recipe and cannot be removed.",
            "error",
        )
        return _location_items_redirect(location_id, page, per_page)

    item_name = record.item.name
    db.session.delete(record)
    db.session.commit()
    log_activity(
        f"Removed item {item_name} from location {location_obj.name}"
    )
    flash("Item removed from location.", "success")
    return _location_items_redirect(location_id, page, per_page)


@location.route("/locations")
@login_required
def view_locations():
    """List all locations."""
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    name_query = request.args.get("name_query", "")
    match_mode = request.args.get("match_mode", "contains")
    archived = request.args.get("archived", "active")

    query = Location.query.options(selectinload(Location.current_menu))
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

    locations = query.order_by(Location.name).paginate(
        page=page, per_page=per_page
    )
    delete_form = DeleteForm()
    return render_template(
        "locations/view_locations.html",
        locations=locations,
        delete_form=delete_form,
        name_query=name_query,
        match_mode=match_mode,
        archived=archived,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
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
