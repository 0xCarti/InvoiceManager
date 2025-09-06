import os

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
from werkzeug.utils import secure_filename

from app import db
from app.forms import ImportItemsForm, ItemForm
from app.models import Item, ItemUnit, LocationStandItem
from app.utils.activity import log_activity

item = Blueprint("item", __name__)

# Constants for the import_items route
# Only plain text files are allowed and uploads are capped at 1MB
ALLOWED_IMPORT_EXTENSIONS = {".txt"}
MAX_IMPORT_SIZE = 1 * 1024 * 1024  # 1 MB


@item.route("/items")
@login_required
def view_items():
    """Display the inventory item list."""
    page = request.args.get("page", 1, type=int)
    items = (
        Item.query.filter_by(archived=False)
        .order_by(Item.name)
        .paginate(page=page, per_page=20)
    )
    form = ItemForm()
    return render_template("items/view_items.html", items=items, form=form)


@item.route("/items/<int:item_id>/locations")
@login_required
def item_locations(item_id):
    """Show all locations holding a specific item and their quantities."""
    item_obj = db.session.get(Item, item_id)
    if item_obj is None:
        abort(404)
    page = request.args.get("page", 1, type=int)
    entries = (
        LocationStandItem.query.filter_by(item_id=item_id)
        .paginate(page=page, per_page=20)
    )
    total = (
        db.session.query(db.func.sum(LocationStandItem.expected_count))
        .filter_by(item_id=item_id)
        .scalar()
        or 0
    )
    return render_template(
        "items/item_locations.html",
        item=item_obj,
        entries=entries,
        total=total,
    )


@item.route("/items/add", methods=["GET", "POST"])
@login_required
def add_item():
    """Add a new item to inventory."""
    form = ItemForm()
    if form.validate_on_submit():
        recv_count = sum(
            1
            for uf in form.units
            if uf.form.name.data and uf.form.receiving_default.data
        )
        trans_count = sum(
            1
            for uf in form.units
            if uf.form.name.data and uf.form.transfer_default.data
        )
        if recv_count > 1 or trans_count > 1:
            flash(
                "Only one unit can be set as receiving and transfer default.",
                "error",
            )
            return render_template(
                "items/item_form.html", form=form, title="Add Item"
            )
        item = Item(
            name=form.name.data,
            base_unit=form.base_unit.data,
            gl_code=form.gl_code.data if "gl_code" in request.form else None,
            gl_code_id=(
                form.gl_code_id.data if "gl_code_id" in request.form else None
            ),
            purchase_gl_code_id=form.purchase_gl_code.data or None,
        )
        db.session.add(item)
        db.session.commit()
        receiving_set = False
        transfer_set = False
        for uf in form.units:
            unit_form = uf.form
            if unit_form.name.data:
                receiving_default = (
                    unit_form.receiving_default.data and not receiving_set
                )
                transfer_default = (
                    unit_form.transfer_default.data and not transfer_set
                )
                db.session.add(
                    ItemUnit(
                        item_id=item.id,
                        name=unit_form.name.data,
                        factor=float(unit_form.factor.data),
                        receiving_default=receiving_default,
                        transfer_default=transfer_default,
                    )
                )
                if receiving_default:
                    receiving_set = True
                if transfer_default:
                    transfer_set = True
        db.session.commit()
        log_activity(f"Added item {item.name}")
        flash("Item added successfully!")
        return redirect(url_for("item.view_items"))
    return render_template("items/item_form.html", form=form, title="Add Item")


@item.route("/items/edit/<int:item_id>", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    """Modify an existing item."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    form = ItemForm(obj=item)
    if request.method == "GET":
        form.gl_code.data = item.gl_code
        form.gl_code_id.data = item.gl_code_id
        form.purchase_gl_code.data = item.purchase_gl_code_id
    if form.validate_on_submit():
        recv_count = sum(
            1
            for uf in form.units
            if uf.form.name.data and uf.form.receiving_default.data
        )
        trans_count = sum(
            1
            for uf in form.units
            if uf.form.name.data and uf.form.transfer_default.data
        )
        if recv_count > 1 or trans_count > 1:
            flash(
                "Only one unit can be set as receiving and transfer default.",
                "error",
            )
            return render_template(
                "items/item_form.html", form=form, item=item, title="Edit Item"
            )
        item.name = form.name.data
        item.base_unit = form.base_unit.data
        if "gl_code" in request.form:
            item.gl_code = form.gl_code.data
        if "gl_code_id" in request.form:
            item.gl_code_id = form.gl_code_id.data
        item.purchase_gl_code_id = form.purchase_gl_code.data or None
        ItemUnit.query.filter_by(item_id=item.id).delete()
        receiving_set = False
        transfer_set = False
        for uf in form.units:
            unit_form = uf.form
            if unit_form.name.data:
                receiving_default = (
                    unit_form.receiving_default.data and not receiving_set
                )
                transfer_default = (
                    unit_form.transfer_default.data and not transfer_set
                )
                db.session.add(
                    ItemUnit(
                        item_id=item.id,
                        name=unit_form.name.data,
                        factor=float(unit_form.factor.data),
                        receiving_default=receiving_default,
                        transfer_default=transfer_default,
                    )
                )
                if receiving_default:
                    receiving_set = True
                if transfer_default:
                    transfer_set = True
        db.session.commit()
        log_activity(f"Edited item {item.id}")
        flash("Item updated successfully!")
        return redirect(url_for("item.view_items"))
    return render_template(
        "items/item_form.html", form=form, item=item, title="Edit Item"
    )


@item.route("/items/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_item(item_id):
    """Delete an item from the catalog."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    item.archived = True
    db.session.commit()
    log_activity(f"Archived item {item.id}")
    flash("Item archived successfully!")
    return redirect(url_for("item.view_items"))


@item.route("/items/bulk_delete", methods=["POST"])
@login_required
def bulk_delete_items():
    """Delete multiple items in one request."""
    item_ids = request.form.getlist("item_ids")
    if item_ids:
        Item.query.filter(Item.id.in_(item_ids)).update(
            {"archived": True}, synchronize_session="fetch"
        )
        db.session.commit()
        log_activity(f'Bulk archived items {",".join(item_ids)}')
        flash("Selected items have been archived.", "success")
    else:
        flash("No items selected.", "warning")
    return redirect(url_for("item.view_items"))


@item.route("/items/search", methods=["GET"])
@login_required
def search_items():
    """Search items by name for autocomplete fields."""
    search_term = request.args.get("term", "")
    items = Item.query.filter(Item.name.ilike(f"%{search_term}%")).all()
    items_data = [
        {"id": item.id, "name": item.name} for item in items
    ]  # Create a list of dicts
    return jsonify(items_data)


@item.route("/items/quick_add", methods=["POST"])
@login_required
def quick_add_item():
    """Create a minimal item via AJAX for purchase orders."""
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    base_unit = data.get("base_unit")
    purchase_gl_code = data.get("purchase_gl_code")
    try:
        purchase_gl_code = int(purchase_gl_code)
    except (TypeError, ValueError):
        purchase_gl_code = None
    recv_unit = (data.get("receiving_unit") or "").strip()
    trans_unit = (data.get("transfer_unit") or "").strip()
    try:
        recv_factor = float(data.get("receiving_factor", 0))
    except (TypeError, ValueError):
        recv_factor = 0
    try:
        trans_factor = float(data.get("transfer_factor", 0))
    except (TypeError, ValueError):
        trans_factor = 0
    valid_units = {"ounce", "gram", "each", "millilitre"}
    if (
        not name
        or base_unit not in valid_units
        or not purchase_gl_code
        or not recv_unit
        or recv_factor <= 0
        or not trans_unit
        or trans_factor <= 0
    ):
        return jsonify({"error": "Invalid data"}), 400
    if Item.query.filter_by(name=name, archived=False).first():
        return jsonify({"error": "Item exists"}), 400
    item = Item(
        name=name,
        base_unit=base_unit,
        purchase_gl_code_id=purchase_gl_code,
    )
    db.session.add(item)
    db.session.commit()
    units = {}

    def add_unit(name, factor, receiving=False, transfer=False):
        unit = units.get(name)
        if unit:
            if receiving:
                unit.receiving_default = True
            if transfer:
                unit.transfer_default = True
            # If the unit already exists but a different factor is provided,
            # do not override the original to avoid inconsistencies.
        else:
            units[name] = ItemUnit(
                item_id=item.id,
                name=name,
                factor=float(factor),
                receiving_default=receiving,
                transfer_default=transfer,
            )

    add_unit(base_unit, 1)
    add_unit(recv_unit, recv_factor, receiving=True)
    add_unit(trans_unit, trans_factor, transfer=True)
    db.session.add_all(units.values())
    db.session.commit()
    log_activity(f"Added item {item.name}")
    return jsonify({"id": item.id, "name": item.name})


@item.route("/items/<int:item_id>/units")
@login_required
def item_units(item_id):
    """Return unit options for an item."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    data = {
        "base_unit": item.base_unit,
        "units": [
            {
                "id": u.id,
                "name": u.name,
                "factor": u.factor,
                "receiving_default": u.receiving_default,
                "transfer_default": u.transfer_default,
            }
            for u in item.units
        ],
    }
    return jsonify(data)


@item.route("/items/<int:item_id>/last_cost")
@login_required
def item_last_cost(item_id):
    """Return the last recorded cost for an item."""
    unit_id = request.args.get("unit_id", type=int)
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    factor = 1.0
    if unit_id:
        unit = db.session.get(ItemUnit, unit_id)
        if unit:
            factor = unit.factor
    return jsonify({"cost": (item.cost or 0.0) * factor})


@item.route("/import_items", methods=["GET", "POST"])
@login_required
def import_items():
    """Bulk import items from a text file."""
    form = ImportItemsForm()
    if form.validate_on_submit():
        from run import app

        file = form.file.data
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if ext not in ALLOWED_IMPORT_EXTENSIONS:
            flash("Only .txt files are allowed.", "error")
            return redirect(url_for("item.import_items"))
        if size > MAX_IMPORT_SIZE:
            flash("File is too large.", "error")
            return redirect(url_for("item.import_items"))
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        # Read all unique item names from the uploaded file
        with open(filepath, "r") as file:
            names = {line.strip() for line in file if line.strip()}

        # Fetch existing active items in a single query and build a lookup
        existing_items = Item.query.filter(
            Item.name.in_(names), Item.archived.is_(False)
        ).all()
        existing_lookup = {item.name for item in existing_items}

        # Bulk create only the missing items
        new_items = [Item(name=name) for name in names if name not in existing_lookup]
        if new_items:
            db.session.bulk_save_objects(new_items)
        db.session.commit()
        log_activity("Imported items from file")

        flash("Items imported successfully.", "success")
        return redirect(url_for("item.import_items"))

    return render_template("items/import_items.html", form=form)
