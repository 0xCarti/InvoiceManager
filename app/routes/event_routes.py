import csv
import io
import json
import os
from collections import defaultdict
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from werkzeug.utils import secure_filename

from app import db
from app.forms import (
    EVENT_TYPES,
    EventForm,
    EventLocationConfirmForm,
    EventLocationForm,
    ScanCountForm,
    TerminalSalesUploadForm,
)
from app.models import (
    Event,
    EventLocation,
    EventStandSheetItem,
    Item,
    Location,
    LocationStandItem,
    Product,
    TerminalSale,
)
from app.utils.activity import log_activity

STANDSHEET_PAGE_SIZE = 20


def _chunk_stand_sheet_items(items, chunk_size=STANDSHEET_PAGE_SIZE):
    """Split stand sheet items into page-sized chunks."""

    if not items:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]

event = Blueprint("event", __name__)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_event_filters(source):
    return {
        "type": (source.get("type") or "").strip(),
        "name_contains": (source.get("name_contains") or "").strip(),
        "name_not_contains": (source.get("name_not_contains") or "").strip(),
        "start_date_from": (source.get("start_date_from") or "").strip(),
        "start_date_to": (source.get("start_date_to") or "").strip(),
        "end_date_from": (source.get("end_date_from") or "").strip(),
        "end_date_to": (source.get("end_date_to") or "").strip(),
        "closed_status": (source.get("closed_status") or "").strip(),
    }


def _apply_event_filters(query, filters):
    event_type = filters.get("type")
    if event_type:
        query = query.filter_by(event_type=event_type)

    name_contains = filters.get("name_contains")
    if name_contains:
        query = query.filter(Event.name.ilike(f"%{name_contains}%"))

    name_not_contains = filters.get("name_not_contains")
    if name_not_contains:
        query = query.filter(~Event.name.ilike(f"%{name_not_contains}%"))

    start_date_from = _parse_date(filters.get("start_date_from"))
    if start_date_from:
        query = query.filter(Event.start_date >= start_date_from)

    start_date_to = _parse_date(filters.get("start_date_to"))
    if start_date_to:
        query = query.filter(Event.start_date <= start_date_to)

    end_date_from = _parse_date(filters.get("end_date_from"))
    if end_date_from:
        query = query.filter(Event.end_date >= end_date_from)

    end_date_to = _parse_date(filters.get("end_date_to"))
    if end_date_to:
        query = query.filter(Event.end_date <= end_date_to)

    closed_status = filters.get("closed_status")
    if closed_status == "open":
        query = query.filter(Event.closed.is_(False))
    elif closed_status == "closed":
        query = query.filter(Event.closed.is_(True))

    return query


@event.route("/events")
@login_required
def view_events():
    filters = _get_event_filters(request.args)
    query = _apply_event_filters(Event.query, filters)
    events = query.all()
    create_form = EventForm()
    return render_template(
        "events/view_events.html",
        events=events,
        event_types=EVENT_TYPES,
        type_labels=dict(EVENT_TYPES),
        create_form=create_form,
        filter_values=filters,
    )


@event.route("/events/create", methods=["GET", "POST"])
@login_required
def create_event():
    form = EventForm()
    if form.validate_on_submit():
        ev = Event(
            name=form.name.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            event_type=form.event_type.data,
            estimated_sales=form.estimated_sales.data,
        )
        db.session.add(ev)
        db.session.commit()
        log_activity(f"Created event {ev.id}")
        flash("Event created")
        return redirect(url_for("event.view_events"))
    return render_template("events/create_event.html", form=form)


@event.route("/events/filter", methods=["POST"])
@login_required
def filter_events_ajax():
    filters = _get_event_filters(request.form)
    events = _apply_event_filters(Event.query, filters).all()
    return render_template(
        "events/_events_table.html",
        events=events,
        type_labels=dict(EVENT_TYPES),
    )


@event.route("/events/create/ajax", methods=["POST"])
@login_required
def create_event_ajax():
    form = EventForm()
    if form.validate_on_submit():
        ev = Event(
            name=form.name.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            event_type=form.event_type.data,
            estimated_sales=form.estimated_sales.data,
        )
        db.session.add(ev)
        db.session.commit()
        log_activity(f"Created event {ev.id}")
        return render_template(
            "events/_event_row.html", e=ev, type_labels=dict(EVENT_TYPES)
        )
    return "Invalid data", 400


@event.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    form = EventForm(obj=ev)
    if form.validate_on_submit():
        ev.name = form.name.data
        ev.start_date = form.start_date.data
        ev.end_date = form.end_date.data
        ev.event_type = form.event_type.data
        ev.estimated_sales = form.estimated_sales.data
        db.session.commit()
        log_activity(f"Edited event {ev.id}")
        flash("Event updated")
        return redirect(url_for("event.view_events"))
    return render_template("events/edit_event.html", form=form, event=ev)


@event.route("/events/<int:event_id>/delete")
@login_required
def delete_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    event_id = ev.id
    db.session.delete(ev)
    db.session.commit()
    log_activity(f"Deleted event {event_id}")
    flash("Event deleted")
    return redirect(url_for("event.view_events"))


@event.route("/events/<int:event_id>")
@login_required
def view_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    type_labels = dict(EVENT_TYPES)
    return render_template(
        "events/view_event.html",
        event=ev,
        event_type_label=type_labels.get(ev.event_type, ev.event_type),
    )


@event.route("/events/<int:event_id>/add_location", methods=["GET", "POST"])
@login_required
def add_location(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    form = EventLocationForm(event_id=event_id)
    if not form.location_id.choices:
        flash("All available locations have already been assigned to this event.")
        return redirect(url_for("event.view_event", event_id=event_id))
    if form.validate_on_submit():
        selected_ids = form.location_id.data
        event_locations = [
            EventLocation(event_id=event_id, location_id=location_id)
            for location_id in selected_ids
        ]
        db.session.add_all(event_locations)
        db.session.commit()
        location_names = []
        for location_id in selected_ids:
            location = db.session.get(Location, location_id)
            location_names.append(location.name if location else str(location_id))
        location_list = ", ".join(location_names)
        log_activity(
            f"Assigned locations {location_list} to event {event_id}"
        )
        flash(
            "Locations assigned"
            if len(event_locations) > 1
            else "Location assigned"
        )
        return redirect(url_for("event.view_event", event_id=event_id))
    return render_template("events/add_location.html", form=form, event=ev)


@event.route(
    "/events/<int:event_id>/locations/<int:el_id>/sales/add",
    methods=["GET", "POST"],
)
@login_required
def add_terminal_sale(event_id, el_id):
    el = db.session.get(EventLocation, el_id)
    if el is None or el.event_id != event_id:
        abort(404)
    if el.confirmed or el.event.closed:
        flash("This location is closed and cannot accept new sales.")
        return redirect(url_for("event.view_event", event_id=event_id))
    if request.method == "POST":
        updated = False
        for product in el.location.products:
            qty = request.form.get(f"qty_{product.id}")
            try:
                amount = float(qty) if qty else 0
            except ValueError:
                amount = 0

            sale = TerminalSale.query.filter_by(
                event_location_id=el_id, product_id=product.id
            ).first()

            if amount:
                if sale:
                    if sale.quantity != amount:
                        sale.quantity = amount
                        updated = True
                else:
                    sale = TerminalSale(
                        event_location_id=el_id,
                        product_id=product.id,
                        quantity=amount,
                        sold_at=datetime.utcnow(),
                    )
                    db.session.add(sale)
                    updated = True
            elif sale:
                db.session.delete(sale)
                updated = True

        db.session.commit()
        if updated:
            log_activity(f"Updated terminal sales for event location {el_id}")
        flash("Sales recorded")
        return redirect(url_for("event.view_event", event_id=event_id))

    existing_sales = {s.product_id: s.quantity for s in el.terminal_sales}
    return render_template(
        "events/add_terminal_sales.html",
        event_location=el,
        existing_sales=existing_sales,
    )


def _wants_json_response() -> bool:
    """Return True when the current request prefers a JSON response."""

    if request.is_json:
        return True
    accept_mimetypes = request.accept_mimetypes
    return (
        accept_mimetypes["application/json"]
        > accept_mimetypes["text/html"]
    )


def _serialize_scan_totals(event_location: EventLocation):
    """Return the location and summaries of counted items."""

    location, stand_items = _get_stand_items(
        event_location.location_id, event_location.event_id
    )
    totals = []
    seen_item_ids = set()

    for entry in stand_items:
        item = entry["item"]
        sheet = entry.get("sheet")
        counted = float(sheet.closing_count or 0.0) if sheet else 0.0
        totals.append(
            {
                "item_id": item.id,
                "name": item.name,
                "upc": item.upc,
                "expected": float(entry.get("expected") or 0.0),
                "counted": counted,
                "base_unit": item.base_unit,
            }
        )
        seen_item_ids.add(item.id)

    for sheet in event_location.stand_sheet_items:
        if sheet.item_id in seen_item_ids:
            continue
        item = sheet.item
        totals.append(
            {
                "item_id": item.id,
                "name": item.name,
                "upc": item.upc,
                "expected": 0.0,
                "counted": float(sheet.closing_count or 0.0),
                "base_unit": item.base_unit,
            }
        )

    totals.sort(key=lambda record: record["name"].lower())
    return location, totals


@event.route(
    "/events/<int:event_id>/locations/<int:location_id>/scan_counts",
    methods=["GET", "POST"],
)
@login_required
def scan_counts(event_id, location_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    if ev.event_type != "inventory":
        abort(404)

    el = EventLocation.query.filter_by(
        event_id=event_id, location_id=location_id
    ).first()
    if el is None:
        abort(404)

    wants_json = _wants_json_response()

    if ev.closed:
        if wants_json:
            return (
                jsonify(
                    success=False, error="This event is closed to updates."
                ),
                403,
            )
        abort(403, description="This event is closed to updates.")

    form = ScanCountForm()
    if form.quantity.data is None:
        form.quantity.data = 1

    if request.method == "GET" and wants_json:
        location, totals = _serialize_scan_totals(el)
        return jsonify(
            success=True,
            location={"id": location.id, "name": location.name},
            totals=totals,
        )

    if request.method == "POST":
        if wants_json:
            payload = request.get_json(silent=True) or {}
            upc = (payload.get("upc") or "").strip()
            raw_quantity = payload.get("quantity", 1)
            try:
                quantity = float(raw_quantity)
            except (TypeError, ValueError):
                quantity = None

            if not upc:
                return (
                    jsonify(success=False, error="A UPC value is required."),
                    400,
                )
            if quantity is None:
                return (
                    jsonify(
                        success=False,
                        error="Quantity must be a numeric value.",
                    ),
                    400,
                )
        else:
            if not form.validate_on_submit():
                location, totals = _serialize_scan_totals(el)
                return (
                    render_template(
                        "events/scan_count.html",
                        event=ev,
                        location=location,
                        form=form,
                        totals=totals,
                    ),
                    400,
                )
            upc = (form.upc.data or "").strip()
            quantity = float(form.quantity.data or 0)

        item = Item.query.filter_by(upc=upc).first()
        if item is None:
            if wants_json:
                return (
                    jsonify(
                        success=False,
                        error=f"No item found for UPC {upc}.",
                    ),
                    404,
                )
            flash(f"No item found for UPC {upc}.", "danger")
            location, totals = _serialize_scan_totals(el)
            return (
                render_template(
                    "events/scan_count.html",
                    event=ev,
                    location=location,
                    form=form,
                    totals=totals,
                ),
                404,
            )

        sheet = EventStandSheetItem.query.filter_by(
            event_location_id=el.id, item_id=item.id
        ).first()
        if sheet is None:
            sheet = EventStandSheetItem(
                event_location_id=el.id, item_id=item.id
            )
            db.session.add(sheet)

        sheet.transferred_out = (sheet.transferred_out or 0.0) + quantity
        sheet.closing_count = (sheet.closing_count or 0.0) + quantity
        db.session.commit()
        log_activity(
            f"Recorded scan count for event {event_id}"
            f" location {location_id} item {item.id}"
        )

        location, totals = _serialize_scan_totals(el)

        if wants_json:
            return jsonify(
                success=True,
                item={
                    "id": item.id,
                    "name": item.name,
                    "upc": item.upc,
                    "quantity": quantity,
                    "total": float(sheet.transferred_out or 0.0),
                    "base_unit": item.base_unit,
                },
                totals=totals,
            )

        flash(
            f"Recorded {quantity:g} {item.base_unit} for {item.name}.",
            "success",
        )
        return redirect(
            url_for(
                "event.scan_counts",
                event_id=event_id,
                location_id=location_id,
            )
        )

    location, totals = _serialize_scan_totals(el)
    return render_template(
        "events/scan_count.html",
        event=ev,
        location=location,
        form=form,
        totals=totals,
    )


@event.route("/events/<int:event_id>/sales/upload", methods=["GET", "POST"])
@login_required
def upload_terminal_sales(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)

    form = TerminalSalesUploadForm()
    unmatched = []
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        rows = []

        def add_row(loc, name, qty):
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                return
            rows.append((loc, name.strip(), qty))

        if ext == ".xls" or ext == ".xlsx":
            import pandas as pd

            # Use openpyxl for reading Excel files regardless of extension.
            # This avoids reliance on the deprecated xlrd/xlwt packages and
            # allows test fixtures to rename .xlsx files with a .xls suffix.
            df = pd.read_excel(filepath, header=None, engine="openpyxl")
            current_loc = None
            for _, r in df.iterrows():
                first, second = r.iloc[0], r.iloc[1]
                if pd.isna(second):
                    if isinstance(first, str):
                        current_loc = first.strip()
                else:
                    if current_loc and isinstance(second, str):
                        add_row(current_loc, second, r.iloc[4])
        elif ext == ".pdf":
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
            current_loc = None
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if not line[0].isdigit():
                    current_loc = line
                    continue
                if current_loc is None:
                    continue
                parts = line.split()
                idx = 1
                while (
                    idx < len(parts)
                    and not parts[idx].replace(".", "", 1).isdigit()
                ):
                    idx += 1
                if idx + 2 < len(parts):
                    name = " ".join(parts[1:idx])
                    qty = parts[idx + 2]
                    add_row(current_loc, name, qty)

        product_names = {prod_name for _, prod_name, _ in rows}
        product_lookup = {
            p.name: p
            for p in Product.query.filter(
                Product.name.in_(product_names)
            ).all()
        }

        for loc_name, prod_name, qty in rows:
            loc = (
                Location.query.join(EventLocation)
                .filter(
                    EventLocation.event_id == event_id,
                    Location.name == loc_name,
                )
                .first()
            )
            if not loc:
                if loc_name not in unmatched:
                    unmatched.append(loc_name)
                continue
            el = EventLocation.query.filter_by(
                event_id=event_id, location_id=loc.id
            ).first()
            if not el:
                if loc_name not in unmatched:
                    unmatched.append(loc_name)
                continue
            product = product_lookup.get(prod_name)
            if not product:
                continue
            sale = TerminalSale.query.filter_by(
                event_location_id=el.id, product_id=product.id
            ).first()
            if sale:
                sale.quantity = qty
            else:
                db.session.add(
                    TerminalSale(
                        event_location_id=el.id,
                        product_id=product.id,
                        quantity=qty,
                        sold_at=datetime.utcnow(),
                    )
                )
        db.session.commit()
        if rows:
            log_activity(
                f"Uploaded terminal sales for event {event_id} from {filename}"
            )

    return render_template(
        "events/upload_terminal_sales.html",
        form=form,
        event=ev,
        unmatched=unmatched,
    )


@event.route(
    "/events/<int:event_id>/locations/<int:el_id>/confirm",
    methods=["GET", "POST"],
)
@login_required
def confirm_location(event_id, el_id):
    el = db.session.get(EventLocation, el_id)
    if el is None or el.event_id != event_id:
        abort(404)
    form = EventLocationConfirmForm()
    if form.validate_on_submit():
        el.confirmed = True
        db.session.commit()
        log_activity(
            f"Confirmed event location {el_id} for event {event_id}"
        )
        flash("Location confirmed")
        return redirect(url_for("event.view_event", event_id=event_id))
    return render_template(
        "events/confirm_location.html", form=form, event_location=el
    )


def _get_stand_items(location_id, event_id=None):
    location = db.session.get(Location, location_id)
    stand_items = []
    seen = set()

    sales_by_item = {}
    sheet_map = {}
    if event_id is not None:
        el = EventLocation.query.filter_by(
            event_id=event_id,
            location_id=location_id,
        ).first()
        if el:
            for sale in el.terminal_sales:
                for ri in sale.product.recipe_items:
                    if ri.countable:
                        factor = ri.unit.factor if ri.unit else 1
                        sales_by_item[ri.item_id] = (
                            sales_by_item.get(ri.item_id, 0)
                            + sale.quantity * ri.quantity * factor
                        )
            for sheet in el.stand_sheet_items:
                sheet_map[sheet.item_id] = sheet

    for product_obj in location.products:
        for recipe_item in product_obj.recipe_items:
            if recipe_item.countable and recipe_item.item_id not in seen:
                seen.add(recipe_item.item_id)
                record = LocationStandItem.query.filter_by(
                    location_id=location_id,
                    item_id=recipe_item.item_id,
                ).first()
                expected = record.expected_count if record else 0
                sales = sales_by_item.get(recipe_item.item_id, 0)
                item = recipe_item.item
                recv_unit = next(
                    (u for u in item.units if u.receiving_default), None
                )
                trans_unit = next(
                    (u for u in item.units if u.transfer_default), None
                )
                stand_items.append(
                    {
                        "item": item,
                        "expected": expected,
                        "sales": sales,
                        "sheet": sheet_map.get(recipe_item.item_id),
                        "recv_unit": recv_unit,
                        "trans_unit": trans_unit,
                    }
                )

    # Include any items directly assigned to the location that may not be
    # part of a product recipe (e.g. items received via purchase invoices).
    for record in LocationStandItem.query.filter_by(
        location_id=location_id
    ).all():
        if record.item_id in seen:
            continue
        item = record.item
        recv_unit = next((u for u in item.units if u.receiving_default), None)
        trans_unit = next((u for u in item.units if u.transfer_default), None)
        stand_items.append(
            {
                "item": item,
                "expected": record.expected_count,
                "sales": sales_by_item.get(record.item_id, 0),
                "sheet": sheet_map.get(record.item_id),
                "recv_unit": recv_unit,
                "trans_unit": trans_unit,
            }
        )
        seen.add(record.item_id)

    return location, stand_items


def build_sustainability_report(event_id: int) -> dict:
    """Aggregate waste, cost, and carbon metrics for an event."""

    carbon_per_unit = float(
        current_app.config.get("CARBON_EQ_PER_UNIT", 0.5)
    )
    query = (
        db.session.query(
            EventStandSheetItem,
            EventLocation,
            Location,
            Item,
        )
        .join(EventStandSheetItem.event_location)
        .join(EventLocation.location)
        .join(EventStandSheetItem.item)
        .filter(EventLocation.event_id == event_id)
    )

    totals = {"waste": 0.0, "cost": 0.0, "carbon": 0.0}
    location_totals = defaultdict(
        lambda: {"waste": 0.0, "cost": 0.0, "carbon": 0.0}
    )
    item_totals = defaultdict(lambda: {"waste": 0.0, "cost": 0.0, "carbon": 0.0})

    for sheet, _, location, item in query.all():
        eaten = sheet.eaten or 0.0
        spoiled = sheet.spoiled or 0.0
        waste_units = eaten + spoiled
        if waste_units == 0:
            continue

        unit_cost = item.cost or 0.0
        carbon_factor = getattr(item, "carbon_factor", None)
        if carbon_factor is None:
            carbon_factor = carbon_per_unit

        waste_cost = waste_units * unit_cost
        carbon_eq = waste_units * carbon_factor

        totals["waste"] += waste_units
        totals["cost"] += waste_cost
        totals["carbon"] += carbon_eq

        loc_bucket = location_totals[location.name]
        loc_bucket["waste"] += waste_units
        loc_bucket["cost"] += waste_cost
        loc_bucket["carbon"] += carbon_eq

        item_bucket = item_totals[item.name]
        item_bucket["waste"] += waste_units
        item_bucket["cost"] += waste_cost
        item_bucket["carbon"] += carbon_eq

    location_breakdown = [
        {
            "location": name,
            "waste": values["waste"],
            "cost": values["cost"],
            "carbon": values["carbon"],
        }
        for name, values in sorted(
            location_totals.items(), key=lambda item: item[1]["waste"], reverse=True
        )
    ]

    item_leaderboard = [
        {
            "item": name,
            "waste": values["waste"],
            "cost": values["cost"],
            "carbon": values["carbon"],
        }
        for name, values in sorted(
            item_totals.items(), key=lambda item: item[1]["waste"], reverse=True
        )
    ]

    goal_target = float(
        current_app.config.get("SUSTAINABILITY_WASTE_GOAL", 0) or 0.0
    )
    goal_progress = None
    goal_remaining = None
    goal_met = None
    if goal_target > 0:
        goal_remaining = max(goal_target - totals["waste"], 0.0)
        consumed_pct = min((totals["waste"] / goal_target) * 100, 100)
        goal_progress = round(100 - consumed_pct, 2)
        goal_met = totals["waste"] <= goal_target

    chart_data = {
        "labels": [entry["location"] for entry in location_breakdown],
        "datasets": [
            {
                "label": "Waste (units)",
                "backgroundColor": "#198754",
                "data": [entry["waste"] for entry in location_breakdown],
            },
            {
                "label": "Carbon (kg CO₂e)",
                "backgroundColor": "#0d6efd",
                "data": [entry["carbon"] for entry in location_breakdown],
            },
        ],
    }

    return {
        "totals": totals,
        "location_breakdown": location_breakdown,
        "item_leaderboard": item_leaderboard,
        "goal": {
            "target": goal_target if goal_target > 0 else None,
            "remaining": goal_remaining,
            "progress_pct": goal_progress,
            "met": goal_met,
        },
        "chart_data": chart_data,
    }


@event.route(
    "/events/<int:event_id>/stand_sheet/<int:location_id>",
    methods=["GET", "POST"],
)
@login_required
def stand_sheet(event_id, location_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    el = EventLocation.query.filter_by(
        event_id=event_id, location_id=location_id
    ).first()
    if el is None:
        abort(404)
    if el.confirmed or ev.closed:
        flash(
            "This location is closed and the stand sheet cannot be modified."
        )
        return redirect(url_for("event.view_event", event_id=event_id))

    location, stand_items = _get_stand_items(location_id, event_id)

    if request.method == "POST":
        for entry in stand_items:
            item_id = entry["item"].id
            sheet = EventStandSheetItem.query.filter_by(
                event_location_id=el.id,
                item_id=item_id,
            ).first()
            if not sheet:
                sheet = EventStandSheetItem(
                    event_location_id=el.id, item_id=item_id
                )
                db.session.add(sheet)
            sheet.opening_count = (
                request.form.get(f"open_{item_id}", type=float, default=0) or 0
            )
            sheet.transferred_in = (
                request.form.get(f"in_{item_id}", type=float, default=0) or 0
            )
            sheet.transferred_out = (
                request.form.get(f"out_{item_id}", type=float, default=0) or 0
            )
            sheet.eaten = (
                request.form.get(f"eaten_{item_id}", type=float, default=0)
                or 0
            )
            sheet.spoiled = (
                request.form.get(f"spoiled_{item_id}", type=float, default=0)
                or 0
            )
            sheet.closing_count = (
                request.form.get(f"close_{item_id}", type=float, default=0)
                or 0
            )
        db.session.commit()
        log_activity(
            f"Updated stand sheet for event {event_id} location {location_id}"
        )
        flash("Stand sheet saved")
        location, stand_items = _get_stand_items(location_id, event_id)

    return render_template(
        "events/stand_sheet.html",
        event=ev,
        location=location,
        stand_items=stand_items,
    )


@event.route("/events/<int:event_id>/sustainability")
@login_required
def sustainability_dashboard(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)

    report = build_sustainability_report(event_id)
    chart_json = json.dumps(report["chart_data"])

    return render_template(
        "events/sustainability_dashboard.html",
        event=ev,
        report=report,
        chart_json=chart_json,
        print_view=False,
    )


@event.route("/events/<int:event_id>/sustainability/print")
@login_required
def sustainability_dashboard_print(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)

    report = build_sustainability_report(event_id)
    chart_json = json.dumps(report["chart_data"])

    return render_template(
        "events/sustainability_dashboard.html",
        event=ev,
        report=report,
        chart_json=chart_json,
        print_view=True,
    )


@event.route("/events/<int:event_id>/sustainability/export.csv")
@login_required
def sustainability_dashboard_csv(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)

    report = build_sustainability_report(event_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Location", "Waste (units)", "Cost", "Carbon (kg CO₂e)"])
    for entry in report["location_breakdown"]:
        writer.writerow(
            [
                entry["location"],
                f"{entry['waste']:.2f}",
                f"{entry['cost']:.2f}",
                f"{entry['carbon']:.2f}",
            ]
        )

    writer.writerow([])
    writer.writerow(["Item", "Waste (units)", "Cost", "Carbon (kg CO₂e)"])
    for entry in report["item_leaderboard"]:
        writer.writerow(
            [
                entry["item"],
                f"{entry['waste']:.2f}",
                f"{entry['cost']:.2f}",
                f"{entry['carbon']:.2f}",
            ]
        )

    writer.writerow([])
    writer.writerow(["Totals", f"{report['totals']['waste']:.2f}", f"{report['totals']['cost']:.2f}", f"{report['totals']['carbon']:.2f}"])

    csv_response = make_response(output.getvalue())
    csv_response.headers["Content-Type"] = "text/csv"
    filename = f"sustainability-event-{event_id}.csv"
    csv_response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return csv_response


@event.route(
    "/events/<int:event_id>/count_sheet/<int:location_id>",
    methods=["GET", "POST"],
)
@login_required
def count_sheet(event_id, location_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    el = EventLocation.query.filter_by(
        event_id=event_id, location_id=location_id
    ).first()
    if el is None:
        abort(404)
    if ev.closed:
        flash("This event is closed and cannot be modified.")
        return redirect(url_for("event.view_event", event_id=event_id))

    location, stand_items = _get_stand_items(location_id, event_id)

    if request.method == "POST":
        for entry in stand_items:
            item_id = entry["item"].id
            sheet = EventStandSheetItem.query.filter_by(
                event_location_id=el.id,
                item_id=item_id,
            ).first()
            if not sheet:
                sheet = EventStandSheetItem(
                    event_location_id=el.id, item_id=item_id
                )
                db.session.add(sheet)
            recv_qty = (
                request.form.get(f"recv_{item_id}", type=float, default=0) or 0
            )
            trans_qty = (
                request.form.get(f"trans_{item_id}", type=float, default=0)
                or 0
            )
            base_qty = (
                request.form.get(f"base_{item_id}", type=float, default=0) or 0
            )
            recv_factor = (
                entry["recv_unit"].factor if entry["recv_unit"] else 0
            )
            trans_factor = (
                entry["trans_unit"].factor if entry["trans_unit"] else 0
            )
            total = (
                recv_qty * recv_factor + trans_qty * trans_factor + base_qty
            )
            sheet.opening_count = recv_qty
            sheet.transferred_in = trans_qty
            sheet.transferred_out = base_qty
            sheet.closing_count = total
        db.session.commit()
        log_activity(
            f"Updated count sheet for event {event_id} location {location_id}"
        )
        flash("Count sheet saved")
        return redirect(url_for("event.view_event", event_id=event_id))

    return render_template(
        "events/count_sheet.html",
        event=ev,
        location=location,
        stand_items=stand_items,
    )


@event.route("/events/<int:event_id>/stand_sheets")
@login_required
def bulk_stand_sheets(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    data = []
    for el in ev.locations:
        loc, items = _get_stand_items(el.location_id, event_id)
        chunks = _chunk_stand_sheet_items(items)
        page_count = len(chunks)
        for page_number, chunk in enumerate(chunks, start=1):
            data.append(
                {
                    "location": loc,
                    "stand_items": chunk,
                    "page_number": page_number,
                    "page_count": page_count,
                }
            )
    dt = datetime.now()
    generated_at_local = (
        f"{dt.month}/{dt.day}/{dt.year} {dt.strftime('%I:%M %p').lstrip('0')}"
    )
    return render_template(
        "events/bulk_stand_sheets.html",
        event=ev,
        data=data,
        generated_at_local=generated_at_local,
    )


@event.route("/events/<int:event_id>/count_sheets")
@login_required
def bulk_count_sheets(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    data = []
    for el in ev.locations:
        loc, items = _get_stand_items(el.location_id, event_id)
        chunks = _chunk_stand_sheet_items(items)
        page_count = len(chunks)
        for page_number, chunk in enumerate(chunks, start=1):
            data.append(
                {
                    "location": loc,
                    "stand_items": chunk,
                    "page_number": page_number,
                    "page_count": page_count,
                }
            )
    return render_template(
        "events/bulk_count_sheets.html", event=ev, data=data
    )


@event.route("/events/<int:event_id>/close")
@login_required
def close_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    for el in ev.locations:
        counted_item_ids = set()
        for sheet in el.stand_sheet_items:
            counted_item_ids.add(sheet.item_id)
            lsi = LocationStandItem.query.filter_by(
                location_id=el.location_id, item_id=sheet.item_id
            ).first()
            if not sheet.closing_count:
                if lsi:
                    db.session.delete(lsi)
                continue
            if not lsi:
                lsi = LocationStandItem(
                    location_id=el.location_id,
                    item_id=sheet.item_id,
                    purchase_gl_code_id=sheet.item.purchase_gl_code_id,
                )
                db.session.add(lsi)
            elif (
                lsi.purchase_gl_code_id is None
                and sheet.item.purchase_gl_code_id is not None
            ):
                lsi.purchase_gl_code_id = sheet.item.purchase_gl_code_id
            lsi.expected_count = sheet.closing_count

        if counted_item_ids:
            LocationStandItem.query.filter(
                LocationStandItem.location_id == el.location_id,
                ~LocationStandItem.item_id.in_(counted_item_ids),
            ).delete(synchronize_session=False)
        else:
            LocationStandItem.query.filter_by(
                location_id=el.location_id
            ).delete()

        TerminalSale.query.filter_by(event_location_id=el.id).delete()
    ev.closed = True
    db.session.commit()
    log_activity(f"Closed event {event_id}")
    flash("Event closed")
    return redirect(url_for("event.view_events"))


@event.route("/events/<int:event_id>/inventory_report")
@login_required
def inventory_report(event_id):
    """Display inventory variances and GL code totals for an event."""
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)

    rows = []
    gl_totals = {}
    grand_total = 0.0

    for el in ev.locations:
        loc = el.location
        for sheet in el.stand_sheet_items:
            item = sheet.item
            lsi = LocationStandItem.query.filter_by(
                location_id=loc.id, item_id=item.id
            ).first()
            expected = lsi.expected_count if lsi else 0
            variance = sheet.closing_count - expected
            cost_total = sheet.closing_count * item.cost
            gl_obj = item.purchase_gl_code_for_location(loc.id)
            gl_code = gl_obj.code if gl_obj else "Unassigned"
            rows.append(
                {
                    "location": loc,
                    "item": item,
                    "expected": expected,
                    "actual": sheet.closing_count,
                    "variance": variance,
                    "gl_code": gl_code,
                    "cost_total": cost_total,
                }
            )
            gl_totals[gl_code] = gl_totals.get(gl_code, 0.0) + cost_total
            grand_total += cost_total

    return render_template(
        "events/inventory_report.html",
        event=ev,
        rows=rows,
        gl_totals=gl_totals,
        grand_total=grand_total,
    )
