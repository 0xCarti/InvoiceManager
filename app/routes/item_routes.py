import os

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required
from werkzeug.utils import secure_filename

from sqlalchemy.orm import selectinload

from app import db
from app.forms import CSRFOnlyForm, ImportItemsForm, ItemForm
from app.models import (
    GLCode,
    Invoice,
    InvoiceProduct,
    Item,
    ItemUnit,
    LocationStandItem,
    Product,
    ProductRecipeItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Transfer,
    TransferItem,
    Vendor,
)
from app.utils.activity import log_activity
from app.utils.pagination import build_pagination_args, get_per_page

item = Blueprint("item", __name__)

# Constants for the import_items route
# Only plain text files are allowed and uploads are capped at 1MB
ALLOWED_IMPORT_EXTENSIONS = {".txt"}
MAX_IMPORT_SIZE = 1 * 1024 * 1024  # 1 MB


@item.route("/items")
@login_required
def view_items():
    """Display the inventory item list."""
    if request.args.get("reset"):
        session.pop("item_filters", None)
        return redirect(url_for("item.view_items"))

    if not request.args and "item_filters" in session:
        return redirect(url_for("item.view_items", **session["item_filters"]))

    if request.args:
        session["item_filters"] = request.args.to_dict(flat=False)

    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    name_query = request.args.get("name_query", "")
    match_mode = request.args.get("match_mode", "contains")
    gl_code_ids = [
        int(x) for x in request.args.getlist("gl_code_id") if x.isdigit()
    ]
    archived = request.args.get("archived", "active")
    base_unit = request.args.get("base_unit")
    cost_min = request.args.get("cost_min", type=float)
    cost_max = request.args.get("cost_max", type=float)
    vendor_ids = [
        int(x) for x in request.args.getlist("vendor_id") if x.isdigit()
    ]

    query = Item.query.options(
        selectinload(Item.units),
        selectinload(Item.purchase_gl_code),
        selectinload(Item.gl_code_rel),
    )
    if archived == "active":
        query = query.filter(Item.archived.is_(False))
    elif archived == "archived":
        query = query.filter(Item.archived.is_(True))
    if name_query:
        if match_mode == "exact":
            query = query.filter(Item.name == name_query)
        elif match_mode == "startswith":
            query = query.filter(Item.name.like(f"{name_query}%"))
        elif match_mode == "contains":
            query = query.filter(Item.name.like(f"%{name_query}%"))
        elif match_mode == "not_contains":
            query = query.filter(Item.name.notlike(f"%{name_query}%"))
        else:
            query = query.filter(Item.name.like(f"%{name_query}%"))

    if gl_code_ids:
        query = query.filter(Item.gl_code_id.in_(gl_code_ids))

    if vendor_ids:
        query = (
            query.join(
                PurchaseOrderItem, PurchaseOrderItem.item_id == Item.id
            )
            .join(
                PurchaseOrder,
                PurchaseOrderItem.purchase_order_id == PurchaseOrder.id,
            )
            .filter(PurchaseOrder.vendor_id.in_(vendor_ids))
            .distinct()
        )
    if base_unit:
        query = query.filter(Item.base_unit == base_unit)
    if cost_min is not None and cost_max is not None and cost_min > cost_max:
        flash("Invalid cost range: min cannot be greater than max.", "error")
        session.pop("item_filters", None)
        return redirect(url_for("item.view_items"))
    if cost_min is not None:
        query = query.filter(Item.cost >= cost_min)
    if cost_max is not None:
        query = query.filter(Item.cost <= cost_max)

    items = query.order_by(Item.name).paginate(
        page=page, per_page=per_page, error_out=False
    )
    if items.pages and page > items.pages:
        page = items.pages
        items = query.order_by(Item.name).paginate(
            page=page, per_page=per_page, error_out=False
        )
    extra_pagination = {}
    if "archived" not in request.args:
        extra_pagination["archived"] = archived
    create_form = ItemForm()
    bulk_delete_form = CSRFOnlyForm()
    gl_codes = GLCode.query.order_by(GLCode.code).all()
    base_units = [
        u
        for (u,) in db.session.query(Item.base_unit)
        .distinct()
        .order_by(Item.base_unit)
    ]
    vendors = Vendor.query.order_by(Vendor.first_name, Vendor.last_name).all()
    active_gl_codes = (
        GLCode.query.filter(GLCode.id.in_(gl_code_ids)).all() if gl_code_ids else []
    )
    active_vendors = (
        Vendor.query.filter(Vendor.id.in_(vendor_ids)).all() if vendor_ids else []
    )
    return render_template(
        "items/view_items.html",
        items=items,
        create_form=create_form,
        bulk_delete_form=bulk_delete_form,
        name_query=name_query,
        match_mode=match_mode,
        gl_codes=gl_codes,
        gl_code_ids=gl_code_ids,
        base_units=base_units,
        base_unit=base_unit,
        cost_min=cost_min,
        cost_max=cost_max,
        active_gl_codes=active_gl_codes,
        archived=archived,
        vendors=vendors,
        vendor_ids=vendor_ids,
        active_vendors=active_vendors,
        per_page=per_page,
        pagination_args=build_pagination_args(
            per_page, extra_params=extra_pagination
        ),
    )


@item.route("/items/<int:item_id>")
@login_required
def view_item(item_id):
    """Display details for a single item."""
    item_obj = db.session.get(Item, item_id)
    if item_obj is None:
        abort(404)
    purchase_page = request.args.get("purchase_page", 1, type=int)
    sales_page = request.args.get("sales_page", 1, type=int)
    transfer_page = request.args.get("transfer_page", 1, type=int)
    purchase_per_page = get_per_page("purchase_per_page")
    sales_per_page = get_per_page("sales_per_page")
    transfer_per_page = get_per_page("transfer_per_page")
    purchase_items = (
        PurchaseInvoiceItem.query
        .join(PurchaseInvoice)
        .filter(PurchaseInvoiceItem.item_id == item_id)
        .order_by(PurchaseInvoice.received_date.desc(), PurchaseInvoice.id.desc())
        .paginate(
            page=purchase_page, per_page=purchase_per_page
        )
    )
    sales_items = (
        InvoiceProduct.query
        .join(Invoice, InvoiceProduct.invoice_id == Invoice.id)
        .join(Product, InvoiceProduct.product_id == Product.id, isouter=True)
        .join(ProductRecipeItem, ProductRecipeItem.product_id == Product.id)
        .filter(ProductRecipeItem.item_id == item_id)
        .order_by(Invoice.date_created.desc(), Invoice.id.desc())
        .paginate(
            page=sales_page, per_page=sales_per_page
        )
    )
    transfer_items = (
        TransferItem.query
        .join(Transfer)
        .filter(TransferItem.item_id == item_id)
        .order_by(Transfer.date_created.desc(), Transfer.id.desc())
        .paginate(
            page=transfer_page, per_page=transfer_per_page
        )
    )
    return render_template(
        "items/view_item.html",
        item=item_obj,
        purchase_items=purchase_items,
        sales_items=sales_items,
        transfer_items=transfer_items,
        purchase_per_page=purchase_per_page,
        sales_per_page=sales_per_page,
        transfer_per_page=transfer_per_page,
        purchase_pagination_args=build_pagination_args(
            purchase_per_page,
            page_param="purchase_page",
            per_page_param="purchase_per_page",
        ),
        sales_pagination_args=build_pagination_args(
            sales_per_page,
            page_param="sales_page",
            per_page_param="sales_per_page",
        ),
        transfer_pagination_args=build_pagination_args(
            transfer_per_page,
            page_param="transfer_page",
            per_page_param="transfer_per_page",
        ),
    )


@item.route("/items/<int:item_id>/locations")
@login_required
def item_locations(item_id):
    """Show all locations holding a specific item and their quantities."""
    item_obj = db.session.get(Item, item_id)
    if item_obj is None:
        abort(404)
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    entries = LocationStandItem.query.filter_by(item_id=item_id).paginate(
        page=page, per_page=per_page
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
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
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
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                form_html = render_template("items/item_form.html", form=form)
                return jsonify({"success": False, "form_html": form_html})
            flash(
                "Only one unit can be set as receiving and transfer default.",
                "error",
            )
            return render_template(
                "items/item_form_page.html", form=form, title="Add Item"
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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            row_html = render_template("items/_item_row.html", item=item)
            return jsonify({"success": True, "row_html": row_html, "item_id": item.id})
        flash("Item added successfully!")
        return redirect(url_for("item.view_items"))
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if request.method == "POST":
            form_html = render_template("items/item_form.html", form=form)
            return jsonify({"success": False, "form_html": form_html})
        return render_template("items/item_form.html", form=form)
    return render_template("items/item_form_page.html", form=form, title="Add Item")


@item.route("/items/copy/<int:item_id>")
@login_required
def copy_item(item_id):
    """Provide a pre-filled form for duplicating an item."""
    item = db.session.get(Item, item_id)
    if item is None:
        abort(404)
    form = ItemForm(obj=item)
    form.gl_code.data = item.gl_code
    form.gl_code_id.data = item.gl_code_id
    form.purchase_gl_code.data = item.purchase_gl_code_id
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("items/item_form.html", form=form)
    return render_template("items/item_form_page.html", form=form, title="Add Item")


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
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                form_html = render_template(
                    "items/item_form.html", form=form, item=item
                )
                return jsonify({"success": False, "form_html": form_html})
            flash(
                "Only one unit can be set as receiving and transfer default.",
                "error",
            )
            return render_template(
                "items/item_form_page.html", form=form, item=item, title="Edit Item"
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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            row_html = render_template("items/_item_row.html", item=item)
            return jsonify({"success": True, "row_html": row_html, "item_id": item.id})
        flash("Item updated successfully!")
        return redirect(url_for("item.view_items"))
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if request.method == "POST":
            form_html = render_template("items/item_form.html", form=form, item=item)
            return jsonify({"success": False, "form_html": form_html})
        return render_template("items/item_form.html", form=form, item=item)
    return render_template(
        "items/item_form_page.html", form=form, item=item, title="Edit Item"
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
    items = (
        Item.query.options(selectinload(Item.purchase_gl_code))
        .filter(Item.name.ilike(f"%{search_term}%"))
        .order_by(Item.name)
        .limit(20)
        .all()
    )
    items_data = [
        {
            "id": item.id,
            "name": item.name,
            "gl_code": item.purchase_gl_code.code if item.purchase_gl_code else "",
        }
        for item in items
    ]
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
    raw_units = data.get("units")
    if not isinstance(raw_units, list):
        raw_units = []

    cleaned_units = []
    for unit in raw_units:
        if not isinstance(unit, dict):
            continue
        unit_name = (unit.get("name") or "").strip()
        try:
            unit_factor = float(unit.get("factor", 0))
        except (TypeError, ValueError):
            unit_factor = 0
        receiving_default = bool(unit.get("receiving_default"))
        transfer_default = bool(unit.get("transfer_default"))
        if not unit_name or unit_factor <= 0:
            continue
        if unit_name == base_unit:
            unit_factor = 1.0
        cleaned_units.append(
            {
                "name": unit_name,
                "factor": unit_factor,
                "receiving_default": receiving_default,
                "transfer_default": transfer_default,
            }
        )
    valid_units = {"ounce", "gram", "each", "millilitre"}
    if (
        not name
        or base_unit not in valid_units
        or not purchase_gl_code
        or not cleaned_units
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
    receiving_set = False
    transfer_set = False

    def add_unit(name, factor, receiving=False, transfer=False):
        nonlocal receiving_set, transfer_set
        unit = units.get(name)
        receiving_flag = bool(receiving) and not receiving_set
        transfer_flag = bool(transfer) and not transfer_set
        if unit:
            if receiving_flag:
                unit.receiving_default = True
            if transfer_flag:
                unit.transfer_default = True
        else:
            units[name] = ItemUnit(
                item_id=item.id,
                name=name,
                factor=float(factor),
                receiving_default=receiving_flag,
                transfer_default=transfer_flag,
            )
        if receiving_flag:
            receiving_set = True
        if transfer_flag:
            transfer_set = True

    for unit in cleaned_units:
        add_unit(
            unit["name"],
            unit["factor"],
            receiving=unit["receiving_default"],
            transfer=unit["transfer_default"],
        )

    if base_unit not in units:
        add_unit(base_unit, 1.0)

    base_unit_entry = units.get(base_unit)
    if base_unit_entry:
        base_unit_entry.factor = 1.0

    if not receiving_set:
        add_unit(base_unit, 1.0, receiving=True)
    if not transfer_set:
        add_unit(base_unit, 1.0, transfer=True)

    db.session.add_all(units.values())
    db.session.commit()
    log_activity(f"Added item {item.name}")
    gl = db.session.get(GLCode, purchase_gl_code) if purchase_gl_code else None
    return jsonify({
        "id": item.id,
        "name": item.name,
        "gl_code": gl.code if gl else "",
    })


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
        new_items = [
            Item(name=name) for name in names if name not in existing_lookup
        ]
        if new_items:
            db.session.bulk_save_objects(new_items)
        db.session.commit()
        log_activity("Imported items from file")

        flash("Items imported successfully.", "success")
        return redirect(url_for("item.import_items"))

    return render_template("items/import_items.html", form=form)
