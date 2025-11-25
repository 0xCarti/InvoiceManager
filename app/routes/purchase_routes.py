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
from flask_login import current_user, login_required

from app import db
from app.forms import (
    ConfirmForm,
    DeleteForm,
    PurchaseOrderForm,
    ReceiveInvoiceForm,
    VendorItemAliasResolutionForm,
    load_purchase_gl_code_choices,
)
from app.models import (
    GLCode,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    PurchaseInvoice,
    PurchaseInvoiceDraft,
    PurchaseInvoiceItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemArchive,
    Setting,
    VendorItemAlias,
    Vendor,
)
from app.utils.activity import log_activity
from app.utils.numeric import coerce_float
from app.routes.report_routes import (
    _invoice_gl_code_rows,
    invoice_gl_code_report,
)
from app.utils.forecasting import DemandForecastingHelper
from app.utils.pagination import build_pagination_args, get_per_page
from app.services.purchase_imports import (
    CSVImportError,
    ParsedPurchaseLine,
    parse_purchase_order_csv,
    resolve_vendor_purchase_lines,
    serialize_parsed_line,
    update_or_create_vendor_alias,
)

import datetime
import json

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

purchase = Blueprint("purchase", __name__)


def _purchase_gl_code_choices():
    return (
        GLCode.query.filter(
            or_(GLCode.code.like("5%"), GLCode.code.like("6%"))
        )
        .order_by(GLCode.code)
        .all()
    )


def check_negative_invoice_reverse(invoice_obj):
    """Return warnings if reversing the invoice would cause negative inventory."""
    warnings = []
    for inv_item in invoice_obj.items:
        factor = 1
        if inv_item.unit_id:
            unit = db.session.get(ItemUnit, inv_item.unit_id)
            if unit:
                factor = unit.factor
        itm = db.session.get(Item, inv_item.item_id)
        if itm:
            loc_id = inv_item.location_id or invoice_obj.location_id
            record = LocationStandItem.query.filter_by(
                location_id=loc_id,
                item_id=itm.id,
            ).first()
            current = record.expected_count if record else 0
            new_count = current - inv_item.quantity * factor
            if new_count < 0:
                if record and record.location:
                    location_name = record.location.name
                else:
                    fallback_location = db.session.get(Location, loc_id)
                    if fallback_location:
                        location_name = fallback_location.name
                    else:
                        location_name = invoice_obj.location_name
                warnings.append(
                    f"Reversing this invoice will result in negative inventory for {itm.name} at {location_name}"
                )
        else:
            warnings.append(
                f"Cannot reverse invoice because item '{inv_item.item_name}' no longer exists"
            )
    return warnings


@purchase.route("/purchase_orders", methods=["GET"])
@login_required
def view_purchase_orders():
    """Show purchase orders with optional filters."""
    delete_form = DeleteForm()
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    vendor_id = request.args.get("vendor_id", type=int)
    status = request.args.get("status", "pending")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    raw_item_ids = request.args.getlist("item_id")

    item_ids = []
    for raw_id in raw_item_ids:
        try:
            parsed_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if parsed_id <= 0 or parsed_id in item_ids:
            continue
        item_ids.append(parsed_id)

    selected_items = []
    if item_ids:
        selected_item_records = Item.query.filter(Item.id.in_(item_ids)).all()
        item_lookup = {item.id: item for item in selected_item_records}
        item_ids = [item_id for item_id in item_ids if item_id in item_lookup]
        selected_items = [item_lookup[item_id] for item_id in item_ids]

    start_date = (
        datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        if start_date_str
        else None
    )
    end_date = (
        datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
        if end_date_str
        else None
    )

    query = PurchaseOrder.query

    if status == "pending":
        query = query.filter_by(received=False)
    elif status == "completed":
        query = query.filter_by(received=True)

    if item_ids:
        query = query.filter(
            PurchaseOrder.items.any(
                PurchaseOrderItem.item_id.in_(item_ids)
            )
        )

    if vendor_id:
        query = query.filter(PurchaseOrder.vendor_id == vendor_id)
    if start_date:
        query = query.filter(PurchaseOrder.order_date >= start_date)
    if end_date:
        query = query.filter(PurchaseOrder.order_date <= end_date)

    query = query.options(
        selectinload(PurchaseOrder.vendor),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.product),
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.unit),
    )

    orders = query.order_by(PurchaseOrder.order_date.desc()).paginate(
        page=page, per_page=per_page
    )

    vendors = Vendor.query.filter_by(archived=False).all()
    filter_items = (
        Item.query.filter_by(archived=False)
        .order_by(Item.name)
        .all()
    )
    active_item_ids = {item.id for item in filter_items}
    extra_item_options = [
        item for item in selected_items if item.id not in active_item_ids
    ]
    selected_vendor = db.session.get(Vendor, vendor_id) if vendor_id else None
    return render_template(
        "purchase_orders/view_purchase_orders.html",
        orders=orders,
        delete_form=delete_form,
        vendors=vendors,
        vendor_id=vendor_id,
        start_date=start_date_str,
        end_date=end_date_str,
        status=status,
        selected_vendor=selected_vendor,
        filter_items=filter_items,
        extra_item_options=extra_item_options,
        selected_item_ids=item_ids,
        selected_items=selected_items,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
    )


@purchase.route("/purchase_orders/create", methods=["GET", "POST"])
@login_required
def create_purchase_order():
    """Create a purchase order."""
    form = PurchaseOrderForm()
    parse_errors = []
    prefilled_labels = {}
    parse_requested = request.method == "POST" and request.form.get("parse_csv")
    resolution_requested = (
        request.method == "POST" and request.form.get("step") == "resolve_vendor_aliases"
    )

    def _apply_resolved_lines(resolved_lines):
        nonlocal prefilled_labels
        form.items.min_entries = max(len(resolved_lines), 1)
        while len(form.items) < len(resolved_lines):
            form.items.append_entry()
        for idx, resolved in enumerate(resolved_lines):
            parsed_line = resolved.parsed_line
            form.items[idx].quantity.data = parsed_line.quantity
            form.items[idx].cost.data = resolved.cost
            form.items[idx].position.data = idx
            if resolved.item_id:
                form.items[idx].item.data = resolved.item_id
            if resolved.unit_id:
                form.items[idx].unit.data = resolved.unit_id
            prefilled_labels[idx] = parsed_line.vendor_description

    def _prepare_units_map():
        items = (
            Item.query.options(selectinload(Item.units))
            .filter_by(archived=False)
            .order_by(Item.name)
            .all()
        )
        item_choices = [(itm.id, itm.name) for itm in items]
        units_map = {
            itm.id: [
                {"id": unit.id, "name": unit.name, "receiving_default": unit.receiving_default}
                for unit in itm.units
            ]
            for itm in items
        }
        return item_choices, units_map

    if request.method == "GET":
        seed = session.pop("po_recommendation_seed", None)
        if seed:
            vendor_id = seed.get("vendor_id")
            if vendor_id and vendor_id in [choice[0] for choice in form.vendor.choices]:
                form.vendor.data = vendor_id
            order_date = seed.get("order_date")
            expected_date = seed.get("expected_date")
            if order_date:
                try:
                    form.order_date.data = datetime.datetime.strptime(
                        order_date, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    form.order_date.data = datetime.date.today()
            if expected_date:
                try:
                    form.expected_date.data = datetime.datetime.strptime(
                        expected_date, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    form.expected_date.data = datetime.date.today() + datetime.timedelta(
                        days=1
                    )

            items = seed.get("items", [])
            form.items.min_entries = max(len(items), 1)
            while len(form.items) < len(items):
                form.items.append_entry()
            for idx, entry in enumerate(items):
                if idx >= len(form.items):
                    break
                form.items[idx].item.data = entry.get("item_id")
                form.items[idx].unit.data = entry.get("unit_id")
                form.items[idx].quantity.data = entry.get("quantity")
                form.items[idx].cost.data = entry.get("cost")
                form.items[idx].position.data = idx

    if request.method == "GET" and form.order_date.data is None:
        form.order_date.data = datetime.date.today()
    if request.method == "GET" and form.expected_date.data is None:
        form.expected_date.data = datetime.date.today() + datetime.timedelta(days=1)

    if resolution_requested:
        resolution_form = VendorItemAliasResolutionForm()
        vendor_id = request.form.get("vendor_id", type=int)
        vendor = db.session.get(Vendor, vendor_id) if vendor_id else None
        if not vendor:
            flash("Select a vendor before resolving uploaded items.", "warning")
            return redirect(url_for("purchase.create_purchase_order"))

        try:
            parsed_payload = json.loads(request.form.get("parsed_payload") or "[]")
            unresolved_payload = json.loads(
                request.form.get("unresolved_payload") or "[]"
            )
        except (TypeError, ValueError):
            flash("Unable to continue the vendor item resolution.", "danger")
            return redirect(url_for("purchase.create_purchase_order"))

        parsed_lines = [
            ParsedPurchaseLine(
                vendor_sku=item.get("vendor_sku"),
                vendor_description=item.get("vendor_description") or "",
                pack_size=item.get("pack_size"),
                quantity=coerce_float(item.get("quantity")) or 0,
                unit_cost=coerce_float(item.get("unit_cost")),
            )
            for item in parsed_payload
        ]

        unresolved_lines = [
            ParsedPurchaseLine(
                vendor_sku=item.get("vendor_sku"),
                vendor_description=item.get("vendor_description") or "",
                pack_size=item.get("pack_size"),
                quantity=coerce_float(item.get("quantity")) or 0,
                unit_cost=coerce_float(item.get("unit_cost")),
            )
            for item in unresolved_payload
        ]

        resolution_form.vendor_id.data = str(vendor.id)
        resolution_form.parsed_payload.data = json.dumps(parsed_payload)
        resolution_form.unresolved_payload.data = json.dumps(unresolved_payload)
        resolution_form.order_date.data = request.form.get("order_date")
        resolution_form.expected_date.data = request.form.get("expected_date")

        resolution_form.rows.min_entries = len(unresolved_lines)
        while len(resolution_form.rows) < len(unresolved_lines):
            resolution_form.rows.append_entry()

        item_choices, units_map = _prepare_units_map()
        codes = _purchase_gl_code_choices()
        for idx, parsed_line in enumerate(unresolved_lines):
            row = resolution_form.rows[idx]
            row.vendor_sku.data = parsed_line.vendor_sku or ""
            row.vendor_description.data = parsed_line.vendor_description or ""
            row.pack_size.data = parsed_line.pack_size or ""
            row.quantity.data = str(parsed_line.quantity)
            if parsed_line.unit_cost is not None:
                row.unit_cost.data = str(parsed_line.unit_cost)
                row.default_cost.data = parsed_line.unit_cost
            row.item_id.choices = item_choices
            row.unit_id.choices = [(0, "—")] + [
                (unit["id"], unit["name"]) for unit_list in units_map.values() for unit in unit_list
            ]

        if resolution_form.validate_on_submit():
            for idx, parsed_line in enumerate(unresolved_lines):
                row = resolution_form.rows[idx]
                item_id = row.item_id.data
                unit_id = row.unit_id.data if row.unit_id.data else None
                default_cost = row.default_cost.data
                if default_cost is None:
                    default_cost = parsed_line.unit_cost
                alias = update_or_create_vendor_alias(
                    vendor=vendor,
                    item_id=item_id,
                    item_unit_id=unit_id,
                    vendor_sku=parsed_line.vendor_sku,
                    vendor_description=parsed_line.vendor_description,
                    pack_size=parsed_line.pack_size,
                    default_cost=float(default_cost) if default_cost is not None else None,
                )
                db.session.add(alias)
            db.session.commit()
            flash("Saved vendor item mappings for this upload.", "success")

            resolved_lines = resolve_vendor_purchase_lines(vendor, parsed_lines)
            _apply_resolved_lines(resolved_lines)
            form.vendor.data = vendor.id
            if resolution_form.order_date.data:
                try:
                    form.order_date.data = datetime.datetime.strptime(
                        resolution_form.order_date.data, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass
            if resolution_form.expected_date.data:
                try:
                    form.expected_date.data = datetime.datetime.strptime(
                        resolution_form.expected_date.data, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass
        else:
            return render_template(
                "purchase_orders/resolve_vendor_items.html",
                form=resolution_form,
                vendor=vendor,
                unresolved_lines=unresolved_lines,
                units_map=units_map,
                gl_codes=codes,
            )

    if parse_requested:
        vendor_id = form.vendor.data
        vendor = db.session.get(Vendor, vendor_id) if vendor_id else None
        if not vendor:
            parse_errors.append("Select a vendor before uploading a CSV file.")
        elif not form.upload.data:
            parse_errors.append("Attach a CSV file to import.")
        else:
            try:
                parsed = parse_purchase_order_csv(form.upload.data, vendor)
                resolved_lines = resolve_vendor_purchase_lines(vendor, parsed.items)
                unresolved_lines = [
                    line
                    for line in resolved_lines
                    if line.alias is None or line.item_id is None
                ]

                if unresolved_lines:
                    resolution_form = VendorItemAliasResolutionForm()
                    item_choices, units_map = _prepare_units_map()
                    codes = _purchase_gl_code_choices()
                    parsed_payload = [
                        serialize_parsed_line(line) for line in parsed.items
                    ]
                    unresolved_payload = [
                        serialize_parsed_line(line.parsed_line)
                        for line in unresolved_lines
                    ]
                    resolution_form.vendor_id.data = str(vendor.id)
                    resolution_form.parsed_payload.data = json.dumps(parsed_payload)
                    resolution_form.unresolved_payload.data = json.dumps(
                        unresolved_payload
                    )
                    if parsed.order_date:
                        resolution_form.order_date.data = parsed.order_date.isoformat()
                    if parsed.expected_date:
                        resolution_form.expected_date.data = (
                            parsed.expected_date.isoformat()
                        )
                    resolution_form.rows.min_entries = len(unresolved_lines)
                    while len(resolution_form.rows) < len(unresolved_lines):
                        resolution_form.rows.append_entry()

                    for idx, unresolved in enumerate(unresolved_lines):
                        row = resolution_form.rows[idx]
                        parsed_line = unresolved.parsed_line
                        row.vendor_sku.data = parsed_line.vendor_sku or ""
                        row.vendor_description.data = (
                            parsed_line.vendor_description or ""
                        )
                        row.pack_size.data = parsed_line.pack_size or ""
                        row.quantity.data = str(parsed_line.quantity)
                        if parsed_line.unit_cost is not None:
                            row.unit_cost.data = str(parsed_line.unit_cost)
                            row.default_cost.data = parsed_line.unit_cost
                        row.item_id.choices = item_choices
                        row.unit_id.choices = [(0, "—")] + [
                            (unit["id"], unit["name"])
                            for unit_list in units_map.values()
                            for unit in unit_list
                        ]

                    return render_template(
                        "purchase_orders/resolve_vendor_items.html",
                        form=resolution_form,
                        vendor=vendor,
                        unresolved_lines=[line.parsed_line for line in unresolved_lines],
                        units_map=units_map,
                        gl_codes=codes,
                        source_filename=getattr(form.upload.data, "filename", None),
                    )

                _apply_resolved_lines(resolved_lines)
                if parsed.order_date:
                    form.order_date.data = parsed.order_date
                if parsed.expected_date:
                    form.expected_date.data = parsed.expected_date
                flash("CSV imported. Review and confirm the items below.", "success")
            except CSVImportError as exc:
                parse_errors.append(str(exc))
            except Exception:
                parse_errors.append(
                    "Unable to parse the CSV file. Confirm the vendor export format and try again."
                )

    if form.validate_on_submit() and not (parse_requested or resolution_requested):
        vendor_record = db.session.get(Vendor, form.vendor.data)
        vendor_name = (
            f"{vendor_record.first_name} {vendor_record.last_name}"
            if vendor_record
            else ""
        )
        po = PurchaseOrder(
            vendor_id=form.vendor.data,
            user_id=current_user.id,
            vendor_name=vendor_name,
            order_date=form.order_date.data,
            expected_date=form.expected_date.data,
            delivery_charge=form.delivery_charge.data or 0.0,
        )
        db.session.add(po)
        db.session.commit()

        item_entries = []
        fallback_counter = 0
        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = coerce_float(request.form.get(f"items-{index}-quantity"))
            unit_cost = coerce_float(request.form.get(f"items-{index}-cost"))
            position = request.form.get(f"items-{index}-position", type=int)
            if item_id and quantity is not None:
                item_entries.append(
                    {
                        "item_id": item_id,
                        "unit_id": unit_id,
                        "quantity": quantity,
                        "unit_cost": unit_cost,
                        "position": position,
                        "fallback": fallback_counter,
                    }
                )
                fallback_counter += 1

        item_entries.sort(
            key=lambda entry: (
                entry["position"]
                if entry["position"] is not None
                else entry["fallback"],
                entry["fallback"],
            )
        )

        for order_index, entry in enumerate(item_entries):
            db.session.add(
                PurchaseOrderItem(
                    purchase_order_id=po.id,
                    item_id=entry["item_id"],
                    unit_id=entry["unit_id"],
                    quantity=entry["quantity"],
                    unit_cost=entry["unit_cost"],
                    position=order_index,
                )
            )

        db.session.commit()
        log_activity(f"Created purchase order {po.id}")
        flash("Purchase order created successfully!", "success")
        return redirect(url_for("purchase.view_purchase_orders"))

    selected_item_ids = []
    for item_form in form.items:
        if item_form.item.data:
            try:
                selected_item_ids.append(int(item_form.item.data))
            except (TypeError, ValueError):
                continue
    item_lookup = {}
    if selected_item_ids:
        item_lookup = {
            item.id: {
                "name": item.name,
                "gl_code": item.purchase_gl_code.code
                if item.purchase_gl_code
                else "",
            }
            for item in Item.query.options(selectinload(Item.purchase_gl_code))
            .filter(Item.id.in_(selected_item_ids))
            .all()
        }

    codes = _purchase_gl_code_choices()
    return render_template(
        "purchase_orders/create_purchase_order.html",
        form=form,
        gl_codes=codes,
        item_lookup=item_lookup,
        parse_errors=parse_errors,
        prefilled_labels=prefilled_labels,
    )


@purchase.route(
    "/purchase_orders/recommendations", methods=["GET", "POST"]
)
@login_required
def purchase_order_recommendations():
    """Display demand-based purchase order recommendations."""

    params = request.values if request.method == "POST" else request.args
    raw_lookback = coerce_float(params.get("lookback_days"))
    lookback_days = int(raw_lookback) if raw_lookback is not None else 0
    if not lookback_days:
        lookback_days = 30
    location_id = params.get("location_id", type=int)
    item_id = params.get("item_id", type=int)
    attendance_multiplier = coerce_float(params.get("attendance_multiplier")) or 1.0
    weather_multiplier = coerce_float(params.get("weather_multiplier")) or 1.0
    promo_multiplier = coerce_float(params.get("promo_multiplier")) or 1.0
    raw_lead_time = coerce_float(params.get("lead_time_days"))
    lead_time_days = int(raw_lead_time) if raw_lead_time is not None else 0
    if not lead_time_days:
        lead_time_days = 3

    helper = DemandForecastingHelper(
        lookback_days=lookback_days, lead_time_days=lead_time_days
    )
    recommendations = helper.build_recommendations(
        location_ids=[location_id] if location_id else None,
        item_ids=[item_id] if item_id else None,
        attendance_multiplier=attendance_multiplier,
        weather_multiplier=weather_multiplier,
        promo_multiplier=promo_multiplier,
    )

    vendors = Vendor.query.filter_by(archived=False).all()
    locations = Location.query.filter_by(archived=False).all()

    wants_json = (
        request.args.get("format") == "json"
        or request.accept_mimetypes["application/json"]
        > request.accept_mimetypes["text/html"]
    )

    if wants_json:
        payload = {
            "meta": {
                "lookback_days": lookback_days,
                "attendance_multiplier": attendance_multiplier,
                "weather_multiplier": weather_multiplier,
                "promo_multiplier": promo_multiplier,
                "lead_time_days": lead_time_days,
            },
            "data": [
                {
                    "item_id": rec.item.id,
                    "item_name": rec.item.name,
                    "location_id": rec.location.id,
                    "location_name": rec.location.name,
                    "history": {
                        key: round(value, 6)
                        for key, value in rec.history.items()
                        if key != "last_activity_ts"
                    },
                    "base_consumption": round(rec.base_consumption, 6),
                    "adjusted_demand": round(rec.adjusted_demand, 6),
                    "recommended_quantity": round(rec.recommended_quantity, 6),
                    "suggested_delivery_date": rec.suggested_delivery_date.isoformat(),
                    "default_unit_id": rec.default_unit_id,
                }
                for rec in recommendations
            ],
        }
        return jsonify(payload)

    chart_rows = [
        {
            "label": f"{rec.item.name} @ {rec.location.name}",
            "recommended": rec.recommended_quantity,
            "consumption": rec.base_consumption,
            "incoming": rec.history["transfer_in_qty"]
            + rec.history["invoice_qty"]
            + rec.history["open_po_qty"],
        }
        for rec in recommendations
    ]

    if request.method == "POST" and request.form.get("action") == "seed":
        selected_keys = request.form.getlist("selected_lines")
        if not selected_keys:
            flash("No recommendation lines were selected.", "warning")
        else:
            seed_items = []
            override_map = {
                key: coerce_float(request.form.get(f"override-{key}"))
                for key in selected_keys
            }
            rec_map = {
                f"{rec.item.id}:{rec.location.id}": rec for rec in recommendations
            }
            for key in selected_keys:
                rec = rec_map.get(key)
                if not rec:
                    continue
                quantity = override_map.get(key)
                if quantity is None or quantity <= 0:
                    quantity = rec.recommended_quantity
                if quantity <= 0:
                    continue
                seed_items.append(
                    {
                        "item_id": rec.item.id,
                        "unit_id": rec.default_unit_id,
                        "quantity": float(quantity),
                    }
                )

            vendor_id = request.form.get("seed_vendor_id", type=int)
            expected_date = request.form.get("seed_expected_date")
            order_date = request.form.get("seed_order_date") or datetime.date.today().isoformat()

            if seed_items and vendor_id:
                session["po_recommendation_seed"] = {
                    "vendor_id": vendor_id,
                    "expected_date": expected_date
                    or (recommendations[0].suggested_delivery_date.isoformat()
                        if recommendations
                        else datetime.date.today().isoformat()),
                    "order_date": order_date,
                    "items": seed_items,
                }
                session.modified = True
                flash("Purchase order draft populated from recommendations.", "success")
                return redirect(url_for("purchase.create_purchase_order"))
            if not vendor_id:
                flash("Select a vendor before creating a draft purchase order.", "warning")
            if not seed_items:
                flash("No recommendation lines were eligible to push to a draft.", "warning")

    today = datetime.date.today()

    return render_template(
        "purchase_orders/recommendations.html",
        recommendations=recommendations,
        vendors=vendors,
        locations=locations,
        selected_vendor=params.get("seed_vendor_id", type=int),
        selected_location=location_id,
        selected_item=item_id,
        lookback_days=lookback_days,
        attendance_multiplier=attendance_multiplier,
        weather_multiplier=weather_multiplier,
        promo_multiplier=promo_multiplier,
        lead_time_days=lead_time_days,
        chart_rows=chart_rows,
        today=today,
    )


@purchase.route("/purchase_orders/edit/<int:po_id>", methods=["GET", "POST"])
@login_required
def edit_purchase_order(po_id):
    """Modify a pending purchase order."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    form = PurchaseOrderForm()
    if form.validate_on_submit():
        po.vendor_id = form.vendor.data
        vendor_record = db.session.get(Vendor, form.vendor.data)
        po.vendor_name = (
            f"{vendor_record.first_name} {vendor_record.last_name}"
            if vendor_record
            else ""
        )
        po.order_date = form.order_date.data
        po.expected_date = form.expected_date.data
        po.delivery_charge = form.delivery_charge.data or 0.0

        PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).delete()

        item_entries = []
        fallback_counter = 0
        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = coerce_float(request.form.get(f"items-{index}-quantity"))
            unit_cost = coerce_float(request.form.get(f"items-{index}-cost"))
            position = request.form.get(f"items-{index}-position", type=int)
            if item_id and quantity is not None:
                item_entries.append(
                    {
                        "item_id": item_id,
                        "unit_id": unit_id,
                        "quantity": quantity,
                        "unit_cost": unit_cost,
                        "position": position,
                        "fallback": fallback_counter,
                    }
                )
                fallback_counter += 1

        item_entries.sort(
            key=lambda entry: (
                entry["position"]
                if entry["position"] is not None
                else entry["fallback"],
                entry["fallback"],
            )
        )

        for order_index, entry in enumerate(item_entries):
            db.session.add(
                PurchaseOrderItem(
                    purchase_order_id=po.id,
                    item_id=entry["item_id"],
                    unit_id=entry["unit_id"],
                    quantity=entry["quantity"],
                    unit_cost=entry["unit_cost"],
                    position=order_index,
                )
            )

        db.session.commit()
        log_activity(f"Edited purchase order {po.id}")
        flash("Purchase order updated successfully!", "success")
        return redirect(url_for("purchase.view_purchase_orders"))

    if request.method == "GET":
        form.vendor.data = po.vendor_id
        form.order_date.data = po.order_date
        form.expected_date.data = po.expected_date
        form.delivery_charge.data = po.delivery_charge
        form.items.min_entries = max(1, len(po.items))
        for i, poi in enumerate(po.items):
            if len(form.items) <= i:
                form.items.append_entry()
        for i, poi in enumerate(po.items):
            form.items[i].item.data = poi.item_id
            form.items[i].unit.data = poi.unit_id
            form.items[i].quantity.data = poi.quantity
            form.items[i].cost.data = poi.unit_cost
            form.items[i].position.data = poi.position

    selected_item_ids = []
    for item_form in form.items:
        if item_form.item.data:
            try:
                selected_item_ids.append(int(item_form.item.data))
            except (TypeError, ValueError):
                continue
    item_lookup = {}
    if selected_item_ids:
        item_lookup = {
            item.id: {
                "name": item.name,
                "gl_code": item.purchase_gl_code.code
                if item.purchase_gl_code
                else "",
            }
            for item in Item.query.options(selectinload(Item.purchase_gl_code))
            .filter(Item.id.in_(selected_item_ids))
            .all()
        }

    codes = _purchase_gl_code_choices()
    return render_template(
        "purchase_orders/edit_purchase_order.html",
        form=form,
        po=po,
        gl_codes=codes,
        item_lookup=item_lookup,
    )


@purchase.route("/purchase_orders/<int:po_id>/delete", methods=["POST"])
@login_required
def delete_purchase_order(po_id):
    """Delete an unreceived purchase order."""
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    if po.received:
        flash(
            "Cannot delete a purchase order that has been received.", "error"
        )
        return redirect(url_for("purchase.view_purchase_orders"))
    db.session.delete(po)
    db.session.commit()
    log_activity(f"Deleted purchase order {po.id}")
    flash("Purchase order deleted successfully!", "success")
    return redirect(url_for("purchase.view_purchase_orders"))


@purchase.route(
    "/purchase_orders/<int:po_id>/receive", methods=["GET", "POST"]
)
@login_required
def receive_invoice(po_id):
    """Receive a purchase order and create an invoice."""
    po = db.session.get(PurchaseOrder, po_id)
    if po is None:
        abort(404)
    form = ReceiveInvoiceForm()
    gl_code_choices = load_purchase_gl_code_choices()
    department_defaults = Setting.get_receive_location_defaults()
    draft = PurchaseInvoiceDraft.query.filter_by(purchase_order_id=po.id).first()
    draft_data = draft.data if draft else None
    if request.method == "GET":
        prefill_items = []
        if draft_data:
            prefill_items = draft_data.get("items", []) or []
        if not prefill_items:
            prefill_items = [
                {
                    "item_id": poi.item_id,
                    "unit_id": poi.unit_id,
                    "quantity": poi.quantity,
                    "position": poi.position,
                    "gl_code_id": None,
                    "cost": poi.unit_cost,
                    "location_id": None,
                }
                for poi in po.items
            ]

        form.items.min_entries = max(1, len(prefill_items))
        while len(form.items) < len(prefill_items):
            form.items.append_entry()

        if draft_data:
            form.invoice_number.data = draft_data.get("invoice_number")
            if draft_data.get("received_date"):
                try:
                    form.received_date.data = datetime.date.fromisoformat(
                        draft_data["received_date"]
                    )
                except ValueError:
                    pass
            if draft_data.get("department"):
                form.department.data = draft_data.get("department")
            if draft_data.get("gst") is not None:
                form.gst.data = draft_data.get("gst")
            if draft_data.get("pst") is not None:
                form.pst.data = draft_data.get("pst")
            if draft_data.get("delivery_charge") is not None:
                form.delivery_charge.data = draft_data.get("delivery_charge")
            invoice_location_id = draft_data.get("location_id")
            if invoice_location_id and any(
                choice_id == invoice_location_id
                for choice_id, _ in form.location_id.choices
            ):
                form.location_id.data = invoice_location_id
        else:
            form.delivery_charge.data = po.delivery_charge
            if not form.received_date.data:
                form.received_date.data = datetime.date.today()

        selected_department = form.department.data or ""
        if not form.location_id.data:
            default_location_id = department_defaults.get(selected_department)
            if default_location_id and any(
                choice_id == default_location_id
                for choice_id, _ in form.location_id.choices
            ):
                form.location_id.data = default_location_id

        location_choices = [(0, "Use Invoice Location")] + [
            (value, label) for value, label in form.location_id.choices
        ]
        for item_form in form.items:
            item_form.item.choices = [
                (i.id, i.name)
                for i in Item.query.filter_by(archived=False).all()
            ]
            item_form.unit.choices = [
                (u.id, u.name) for u in ItemUnit.query.all()
            ]
            item_form.location_id.choices = location_choices
            if item_form.location_id.data is None:
                item_form.location_id.data = 0
            item_form.gl_code.choices = [
                (value, label) for value, label in gl_code_choices
            ]
        for index, item_data in enumerate(prefill_items):
            if index >= len(form.items):
                break
            form.items[index].item.data = item_data.get("item_id")
            form.items[index].unit.data = item_data.get("unit_id")
            if item_data.get("quantity") is not None:
                form.items[index].quantity.data = item_data.get("quantity")
            if item_data.get("cost") is not None:
                form.items[index].cost.data = item_data.get("cost")
            form.items[index].position.data = item_data.get("position")
            gl_code_value = item_data.get("gl_code_id")
            form.items[index].gl_code.data = gl_code_value or 0
            location_value = item_data.get("location_id")
            form.items[index].location_id.data = location_value or 0
    if form.validate_on_submit():
        location_obj = db.session.get(Location, form.location_id.data)
        if not PurchaseOrderItemArchive.query.filter_by(
            purchase_order_id=po.id
        ).first():
            for poi in po.items:
                db.session.add(
                    PurchaseOrderItemArchive(
                        purchase_order_id=po.id,
                        position=poi.position,
                        item_id=poi.item_id,
                        unit_id=poi.unit_id,
                        quantity=poi.quantity,
                        unit_cost=poi.unit_cost,
                    )
                )
            db.session.commit()
        invoice = PurchaseInvoice(
            purchase_order_id=po.id,
            user_id=current_user.id,
            location_id=form.location_id.data,
            vendor_name=po.vendor_name,
            location_name=location_obj.name if location_obj else "",
            received_date=form.received_date.data,
            invoice_number=form.invoice_number.data,
            department=form.department.data or None,
            gst=form.gst.data or 0.0,
            pst=form.pst.data or 0.0,
            delivery_charge=form.delivery_charge.data or 0.0,
        )
        db.session.add(invoice)
        # Flush so the invoice has an ID for related line items without
        # committing the transaction yet. This keeps all updates in a single
        # commit so item cost changes persist reliably.
        db.session.flush()

        item_entries = []
        fallback_counter = 0
        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = coerce_float(request.form.get(f"items-{index}-quantity"))
            cost = coerce_float(request.form.get(f"items-{index}-cost"))
            position = request.form.get(f"items-{index}-position", type=int)
            gl_code_id = request.form.get(f"items-{index}-gl_code", type=int)
            gl_code_id = gl_code_id or None
            line_location_id = request.form.get(
                f"items-{index}-location_id", type=int
            )
            line_location_id = line_location_id or None
            if item_id and quantity is not None and cost is not None:
                item_entries.append(
                    {
                        "item_id": item_id,
                        "unit_id": unit_id,
                        "quantity": quantity,
                        "cost": abs(cost),
                        "position": position,
                        "fallback": fallback_counter,
                        "gl_code_id": gl_code_id,
                        "location_id": line_location_id,
                    }
                )
                fallback_counter += 1

        item_entries.sort(
            key=lambda entry: (
                entry["position"]
                if entry["position"] is not None
                else entry["fallback"],
                entry["fallback"],
            )
        )

        for order_index, entry in enumerate(item_entries):
            item_obj = db.session.get(Item, entry["item_id"])
            unit_obj = (
                db.session.get(ItemUnit, entry["unit_id"]) if entry["unit_id"] else None
            )

            prev_cost = item_obj.cost if item_obj and item_obj.cost else 0.0
            quantity = entry["quantity"]
            cost = entry["cost"]

            db.session.add(
                PurchaseInvoiceItem(
                    invoice_id=invoice.id,
                    item_id=item_obj.id if item_obj else None,
                    unit_id=unit_obj.id if unit_obj else None,
                    item_name=item_obj.name if item_obj else "",
                    unit_name=unit_obj.name if unit_obj else None,
                    quantity=quantity,
                    cost=cost,
                    prev_cost=prev_cost,
                    position=order_index,
                    purchase_gl_code_id=entry["gl_code_id"],
                    location_id=entry["location_id"],
                )
            )

            if item_obj:
                factor = unit_obj.factor if unit_obj and unit_obj.factor else 1
                prev_qty = (
                    db.session.query(
                        db.func.sum(LocationStandItem.expected_count)
                    )
                    .filter(LocationStandItem.item_id == item_obj.id)
                    .scalar()
                    or 0
                )
                new_qty = quantity * factor
                total_qty = prev_qty + new_qty

                # Cost per base unit for the newly received stock
                cost_per_unit = cost / factor if factor else cost
                prev_total_cost = prev_qty * prev_cost
                new_total_cost = cost_per_unit * new_qty
                if total_qty > 0:
                    weighted_cost = (prev_total_cost + new_total_cost) / total_qty
                else:
                    weighted_cost = cost_per_unit

                item_obj.quantity = total_qty
                item_obj.cost = weighted_cost

                # Explicitly mark the item as dirty so cost updates persist
                db.session.add(item_obj)

                line_location_id = entry["location_id"] or invoice.location_id
                record = LocationStandItem.query.filter_by(
                    location_id=line_location_id, item_id=item_obj.id
                ).first()
                if not record:
                    record = LocationStandItem(
                        location_id=line_location_id,
                        item_id=item_obj.id,
                        expected_count=0,
                        purchase_gl_code_id=item_obj.purchase_gl_code_id,
                    )
                    db.session.add(record)
                elif (
                    record.purchase_gl_code_id is None
                    and item_obj.purchase_gl_code_id is not None
                ):
                    record.purchase_gl_code_id = item_obj.purchase_gl_code_id
                record.expected_count += quantity * factor

                # Ensure the in-memory changes are sent to the database so
                # subsequent iterations or queries within this request see
                # the updated cost and quantity values immediately.
                db.session.flush()
        po.received = True
        db.session.add(po)
        if draft:
            db.session.delete(draft)
        # Commit once so that invoice, items, and updated item costs are saved
        # atomically, ensuring the weighted cost persists in the database.
        db.session.commit()
        log_activity(f"Received invoice {invoice.id} for PO {po.id}")
        flash("Invoice received successfully!", "success")
        return redirect(url_for("purchase.view_purchase_invoices"))

    return render_template(
        "purchase_orders/receive_invoice.html",
        form=form,
        po=po,
        gl_code_choices=gl_code_choices,
        department_defaults=department_defaults,
    )


@purchase.route("/purchase_invoices", methods=["GET"])
@login_required
def view_purchase_invoices():
    """List all received purchase invoices."""
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    invoice_number = request.args.get("invoice_number")
    if invoice_number is not None:
        invoice_number = invoice_number.strip()
    if not invoice_number:
        invoice_number = None
    po_number = request.args.get("po_number", type=int)
    vendor_id = request.args.get("vendor_id", type=int)
    location_id = request.args.get("location_id", type=int)
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    amount_filter_raw = request.args.get("amount_filter")
    amount_value_raw = request.args.get("amount_value")

    allowed_amount_filters = {"gt", "lt", "eq"}
    amount_filter = (
        amount_filter_raw if amount_filter_raw in allowed_amount_filters else None
    )
    amount_value = (
        coerce_float(amount_value_raw, default=None)
        if amount_value_raw not in (None, "")
        else None
    )

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.date.fromisoformat(start_date_str)
        except ValueError:
            flash("Invalid start date.", "error")
            return redirect(url_for("purchase.view_purchase_invoices"))
    if end_date_str:
        try:
            end_date = datetime.date.fromisoformat(end_date_str)
        except ValueError:
            flash("Invalid end date.", "error")
            return redirect(url_for("purchase.view_purchase_invoices"))
    if start_date and end_date and start_date > end_date:
        flash("Invalid date range: start cannot be after end.", "error")
        return redirect(url_for("purchase.view_purchase_invoices"))

    raw_item_ids = request.args.getlist("item_id")
    selected_item_ids = []
    seen_item_ids = set()
    for raw_item_id in raw_item_ids:
        try:
            parsed_id = int(raw_item_id)
        except (TypeError, ValueError):
            continue
        if parsed_id in seen_item_ids:
            continue
        seen_item_ids.add(parsed_id)
        selected_item_ids.append(parsed_id)

    items = Item.query.order_by(Item.name).all()
    item_lookup = {item.id: item for item in items}
    selected_items = [
        item_lookup[item_id]
        for item_id in selected_item_ids
        if item_id in item_lookup
    ]
    selected_item_ids = [item.id for item in selected_items]
    selected_item_names = [item.name for item in selected_items]

    query = PurchaseInvoice.query.options(
        selectinload(PurchaseInvoice.purchase_order).selectinload(PurchaseOrder.vendor),
        selectinload(PurchaseInvoice.items)
        .selectinload(PurchaseInvoiceItem.item),
        selectinload(PurchaseInvoice.items)
        .selectinload(PurchaseInvoiceItem.unit),
        selectinload(PurchaseInvoice.items)
        .selectinload(PurchaseInvoiceItem.location),
        selectinload(PurchaseInvoice.items)
        .selectinload(PurchaseInvoiceItem.purchase_gl_code),
    )
    if invoice_number:
        query = query.filter(
            PurchaseInvoice.invoice_number.ilike(f"%{invoice_number}%")
        )
    if po_number:
        query = query.filter(PurchaseInvoice.purchase_order_id == po_number)
    if vendor_id:
        query = query.join(PurchaseOrder).filter(PurchaseOrder.vendor_id == vendor_id)
    if location_id:
        query = query.filter(PurchaseInvoice.location_id == location_id)
    if start_date:
        query = query.filter(PurchaseInvoice.received_date >= start_date)
    if end_date:
        query = query.filter(PurchaseInvoice.received_date <= end_date)
    if selected_item_ids:
        query = query.filter(
            PurchaseInvoice.items.any(
                PurchaseInvoiceItem.item_id.in_(selected_item_ids)
            )
        )

    if amount_filter and amount_value is not None:
        item_totals_subq = (
            db.session.query(
                PurchaseInvoiceItem.invoice_id.label("invoice_id"),
                func.sum(
                    PurchaseInvoiceItem.quantity * PurchaseInvoiceItem.cost
                ).label("item_sum"),
            )
            .group_by(PurchaseInvoiceItem.invoice_id)
            .subquery()
        )

        query = query.outerjoin(
            item_totals_subq, item_totals_subq.c.invoice_id == PurchaseInvoice.id
        )

        total_expression = (
            func.coalesce(item_totals_subq.c.item_sum, 0)
            + func.coalesce(PurchaseInvoice.delivery_charge, 0)
            + func.coalesce(PurchaseInvoice.gst, 0)
            + func.coalesce(PurchaseInvoice.pst, 0)
        )

        if amount_filter == "gt":
            query = query.filter(total_expression > amount_value)
        elif amount_filter == "lt":
            query = query.filter(total_expression < amount_value)
        elif amount_filter == "eq":
            query = query.filter(total_expression == amount_value)

    invoices = query.order_by(
        PurchaseInvoice.received_date.desc(), PurchaseInvoice.id.desc()
    ).paginate(page=page, per_page=per_page)

    vendors = Vendor.query.order_by(Vendor.first_name, Vendor.last_name).all()
    locations = Location.query.order_by(Location.name).all()
    active_vendor = db.session.get(Vendor, vendor_id) if vendor_id else None
    active_location = db.session.get(Location, location_id) if location_id else None

    return render_template(
        "purchase_invoices/view_purchase_invoices.html",
        invoices=invoices,
        vendors=vendors,
        locations=locations,
        invoice_number=invoice_number,
        po_number=po_number,
        vendor_id=vendor_id,
        location_id=location_id,
        start_date=start_date_str,
        end_date=end_date_str,
        active_vendor=active_vendor,
        active_location=active_location,
        items=items,
        selected_items=selected_items,
        selected_item_ids=selected_item_ids,
        selected_item_names=selected_item_names,
        amount_filter=amount_filter,
        amount_value=amount_value,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
    )


@purchase.route("/purchase_invoices/<int:invoice_id>")
@login_required
def view_purchase_invoice(invoice_id):
    """Display a purchase invoice."""
    invoice = (
        PurchaseInvoice.query.options(
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.item),
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.unit),
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.location),
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.purchase_gl_code),
            selectinload(PurchaseInvoice.purchase_order).selectinload(
                PurchaseOrder.vendor
            ),
            selectinload(PurchaseInvoice.location),
        ).get(invoice_id)
    )
    if invoice is None:
        abort(404)
    return render_template(
        "purchase_invoices/view_purchase_invoice.html", invoice=invoice
    )


@purchase.route("/purchase_invoices/<int:invoice_id>/report")
@login_required
def legacy_purchase_invoice_report(invoice_id: int):
    """Backwards compatible endpoint for purchase invoice GL reports."""

    invoice = (
        PurchaseInvoice.query.options(
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.item),
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.purchase_gl_code),
            selectinload(PurchaseInvoice.purchase_order).selectinload(
                PurchaseOrder.vendor
            ),
            selectinload(PurchaseInvoice.location),
        )
        .filter_by(id=invoice_id)
        .first()
    )

    if invoice is None:
        abort(404)

    rows, totals = _invoice_gl_code_rows(invoice)
    report_data = {row["code"]: row for row in rows}

    return render_template(
        "report_invoice_gl_code.html",
        invoice=invoice,
        rows=rows,
        totals=totals,
        report=report_data,
    )


@purchase.route(
    "/purchase_invoices/<int:invoice_id>/reverse", methods=["GET", "POST"]
)
@login_required
def reverse_purchase_invoice(invoice_id):
    """Undo receipt of a purchase invoice."""
    invoice = db.session.get(PurchaseInvoice, invoice_id)
    if invoice is None:
        abort(404)
    po = db.session.get(PurchaseOrder, invoice.purchase_order_id)
    if po is None:
        abort(404)
    warnings = check_negative_invoice_reverse(invoice)
    form = ConfirmForm()
    if warnings and request.method == "GET":
        return render_template(
            "confirm_action.html",
            form=form,
            warnings=warnings,
            action_url=url_for(
                "purchase.reverse_purchase_invoice", invoice_id=invoice_id
            ),
            cancel_url=url_for("purchase.view_purchase_invoices"),
            title="Confirm Invoice Reversal",
        )
    if warnings and not form.validate_on_submit():
        return render_template(
            "confirm_action.html",
            form=form,
            warnings=warnings,
            action_url=url_for(
                "purchase.reverse_purchase_invoice", invoice_id=invoice_id
            ),
            cancel_url=url_for("purchase.view_purchase_invoices"),
            title="Confirm Invoice Reversal",
        )
    draft_payload = {
        "invoice_number": invoice.invoice_number,
        "received_date": invoice.received_date.isoformat()
        if invoice.received_date
        else None,
        "location_id": invoice.location_id,
        "department": invoice.department,
        "gst": invoice.gst,
        "pst": invoice.pst,
        "delivery_charge": invoice.delivery_charge,
        "items": [
            {
                "item_id": inv_item.item_id,
                "unit_id": inv_item.unit_id,
                "quantity": inv_item.quantity,
                "cost": inv_item.cost,
                "position": inv_item.position,
                "gl_code_id": inv_item.purchase_gl_code_id,
                "location_id": inv_item.location_id,
            }
            for inv_item in invoice.items
        ],
    }
    existing_draft = PurchaseInvoiceDraft.query.filter_by(
        purchase_order_id=po.id
    ).first()
    if existing_draft:
        existing_draft.update_payload(draft_payload)
    else:
        db.session.add(
            PurchaseInvoiceDraft(
                purchase_order_id=po.id,
                payload=json.dumps(draft_payload),
            )
        )
    for inv_item in invoice.items:
        factor = 1
        if inv_item.unit_id:
            unit = db.session.get(ItemUnit, inv_item.unit_id)
            if unit:
                factor = unit.factor
        itm = db.session.get(Item, inv_item.item_id)
        if not itm:
            flash(
                f"Cannot reverse invoice because item '{inv_item.item_name}' no longer exists.",
                "error",
            )
            return redirect(url_for("purchase.view_purchase_invoices"))

        removed_qty = inv_item.quantity * factor
        qty_before = itm.quantity
        itm.quantity = qty_before - removed_qty
        itm.cost = inv_item.prev_cost or 0.0

        # Update expected count for the location where items were received
        line_location_id = inv_item.location_id or invoice.location_id
        record = LocationStandItem.query.filter_by(
            location_id=line_location_id,
            item_id=itm.id,
        ).first()
        if not record:
            record = LocationStandItem(
                location_id=line_location_id,
                item_id=itm.id,
                expected_count=0,
                purchase_gl_code_id=itm.purchase_gl_code_id,
            )
            db.session.add(record)
        elif (
            record.purchase_gl_code_id is None
            and itm.purchase_gl_code_id is not None
        ):
            record.purchase_gl_code_id = itm.purchase_gl_code_id
        new_count = record.expected_count - removed_qty
        record.expected_count = new_count

    location_ids = {
        inv_item.location_id or invoice.location_id for inv_item in invoice.items
    }
    missing_locations = [
        loc_id
        for loc_id in location_ids
        if loc_id and not db.session.get(Location, loc_id)
    ]
    if missing_locations:
        flash(
            "Cannot reverse invoice because one or more receiving locations no longer exist.",
            "error",
        )
        return redirect(url_for("purchase.view_purchase_invoices"))

    PurchaseInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
    db.session.delete(invoice)
    po.received = False
    db.session.commit()
    flash("Invoice reversed successfully", "success")
    return redirect(url_for("purchase.view_purchase_orders"))
