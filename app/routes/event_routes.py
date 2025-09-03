from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    current_app,
)
from flask_login import login_required
from app import db
from app.models import Event, EventLocation, TerminalSale, Location, LocationStandItem, Product, EventStandSheetItem
from app.forms import (
    EventForm,
    EventLocationForm,
    EventLocationConfirmForm,
    TerminalSalesUploadForm,
    EVENT_TYPES,
)
from werkzeug.utils import secure_filename
import os
import pandas as pd
import pdfplumber


event = Blueprint("event", __name__)


@event.route("/events")
@login_required
def view_events():
    event_type = request.args.get("type")
    query = Event.query
    if event_type:
        query = query.filter_by(event_type=event_type)
    events = query.all()
    return render_template(
        "events/view_events.html",
        events=events,
        event_type=event_type,
        event_types=EVENT_TYPES,
        type_labels=dict(EVENT_TYPES),
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
        )
        db.session.add(ev)
        db.session.commit()
        flash("Event created")
        return redirect(url_for("event.view_events"))
    return render_template("events/create_event.html", form=form)


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
        db.session.commit()
        flash("Event updated")
        return redirect(url_for("event.view_events"))
    return render_template("events/edit_event.html", form=form, event=ev)


@event.route("/events/<int:event_id>/delete")
@login_required
def delete_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    db.session.delete(ev)
    db.session.commit()
    flash("Event deleted")
    return redirect(url_for("event.view_events"))


@event.route("/events/<int:event_id>")
@login_required
def view_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    return render_template("events/view_event.html", event=ev)


@event.route("/events/<int:event_id>/add_location", methods=["GET", "POST"])
@login_required
def add_location(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    form = EventLocationForm()
    if form.validate_on_submit():
        el = EventLocation(
            event_id=event_id,
            location_id=form.location_id.data,
        )
        db.session.add(el)
        db.session.commit()
        flash("Location assigned")
        return redirect(url_for("event.view_event", event_id=event_id))
    return render_template("events/add_location.html", form=form, event=ev)


@event.route(
    "/events/<int:event_id>/locations/<int:el_id>/sales/add", methods=["GET", "POST"]
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
                    sale.quantity = amount
                else:
                    sale = TerminalSale(
                        event_location_id=el_id,
                        product_id=product.id,
                        quantity=amount,
                    )
                    db.session.add(sale)
            elif sale:
                db.session.delete(sale)

        db.session.commit()
        flash("Sales recorded")
        return redirect(url_for("event.view_event", event_id=event_id))

    existing_sales = {s.product_id: s.quantity for s in el.terminal_sales}
    return render_template(
        "events/add_terminal_sales.html",
        event_location=el,
        existing_sales=existing_sales,
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
            with pdfplumber.open(filepath) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
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
                while idx < len(parts) and not parts[idx].replace(".", "", 1).isdigit():
                    idx += 1
                if idx + 2 < len(parts):
                    name = " ".join(parts[1:idx])
                    qty = parts[idx + 2]
                    add_row(current_loc, name, qty)

        for loc_name, prod_name, qty in rows:
            loc = (
                Location.query.join(EventLocation)
                .filter(EventLocation.event_id == event_id, Location.name == loc_name)
                .first()
            )
            if not loc:
                if loc_name not in unmatched:
                    unmatched.append(loc_name)
                continue
            el = EventLocation.query.filter_by(event_id=event_id, location_id=loc.id).first()
            if not el:
                if loc_name not in unmatched:
                    unmatched.append(loc_name)
                continue
            product = Product.query.filter_by(name=prod_name).first()
            if not product:
                continue
            sale = TerminalSale.query.filter_by(event_location_id=el.id, product_id=product.id).first()
            if sale:
                sale.quantity = qty
            else:
                db.session.add(
                    TerminalSale(event_location_id=el.id, product_id=product.id, quantity=qty)
                )
        db.session.commit()

    return render_template(
        "events/upload_terminal_sales.html",
        form=form,
        event=ev,
        unmatched=unmatched,
    )


@event.route(
    "/events/<int:event_id>/locations/<int:el_id>/confirm", methods=["GET", "POST"]
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
        flash("Location confirmed")
        return redirect(url_for("event.view_event", event_id=event_id))
    return render_template("events/confirm_location.html", form=form, event_location=el)


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
                            sales_by_item.get(ri.item_id, 0) + sale.quantity * ri.quantity * factor
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
                recv_unit = next((u for u in item.units if u.receiving_default), None)
                trans_unit = next((u for u in item.units if u.transfer_default), None)
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
    for record in LocationStandItem.query.filter_by(location_id=location_id).all():
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


@event.route('/events/<int:event_id>/stand_sheet/<int:location_id>', methods=['GET', 'POST'])
@login_required
def stand_sheet(event_id, location_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    el = EventLocation.query.filter_by(event_id=event_id, location_id=location_id).first()
    if el is None:
        abort(404)
    if el.confirmed or ev.closed:
        flash("This location is closed and the stand sheet cannot be modified.")
        return redirect(url_for("event.view_event", event_id=event_id))

    location, stand_items = _get_stand_items(location_id, event_id)

    if request.method == 'POST':
        for entry in stand_items:
            item_id = entry['item'].id
            sheet = EventStandSheetItem.query.filter_by(
                event_location_id=el.id,
                item_id=item_id,
            ).first()
            if not sheet:
                sheet = EventStandSheetItem(event_location_id=el.id, item_id=item_id)
                db.session.add(sheet)
            sheet.opening_count = request.form.get(f'open_{item_id}', type=float, default=0) or 0
            sheet.transferred_in = request.form.get(f'in_{item_id}', type=float, default=0) or 0
            sheet.transferred_out = request.form.get(f'out_{item_id}', type=float, default=0) or 0
            sheet.eaten = request.form.get(f'eaten_{item_id}', type=float, default=0) or 0
            sheet.spoiled = request.form.get(f'spoiled_{item_id}', type=float, default=0) or 0
            sheet.closing_count = request.form.get(f'close_{item_id}', type=float, default=0) or 0
        db.session.commit()
        flash('Stand sheet saved')
        location, stand_items = _get_stand_items(location_id, event_id)

    return render_template(
        'events/stand_sheet.html',
        event=ev,
        location=location,
        stand_items=stand_items,
    )


@event.route('/events/<int:event_id>/count_sheet/<int:location_id>', methods=['GET', 'POST'])
@login_required
def count_sheet(event_id, location_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    el = EventLocation.query.filter_by(event_id=event_id, location_id=location_id).first()
    if el is None:
        abort(404)
    if ev.closed:
        flash('This event is closed and cannot be modified.')
        return redirect(url_for('event.view_event', event_id=event_id))

    location, stand_items = _get_stand_items(location_id, event_id)

    if request.method == 'POST':
        for entry in stand_items:
            item_id = entry['item'].id
            sheet = EventStandSheetItem.query.filter_by(
                event_location_id=el.id,
                item_id=item_id,
            ).first()
            if not sheet:
                sheet = EventStandSheetItem(event_location_id=el.id, item_id=item_id)
                db.session.add(sheet)
            recv_qty = request.form.get(f'recv_{item_id}', type=float, default=0) or 0
            trans_qty = request.form.get(f'trans_{item_id}', type=float, default=0) or 0
            base_qty = request.form.get(f'base_{item_id}', type=float, default=0) or 0
            recv_factor = entry['recv_unit'].factor if entry['recv_unit'] else 0
            trans_factor = entry['trans_unit'].factor if entry['trans_unit'] else 0
            total = recv_qty * recv_factor + trans_qty * trans_factor + base_qty
            sheet.opening_count = recv_qty
            sheet.transferred_in = trans_qty
            sheet.transferred_out = base_qty
            sheet.closing_count = total
        db.session.commit()
        flash('Count sheet saved')
        location, stand_items = _get_stand_items(location_id, event_id)

    return render_template(
        'events/count_sheet.html',
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
        data.append({"location": loc, "stand_items": items})
    return render_template("events/bulk_stand_sheets.html", event=ev, data=data)


@event.route("/events/<int:event_id>/count_sheets")
@login_required
def bulk_count_sheets(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    data = []
    for el in ev.locations:
        loc, items = _get_stand_items(el.location_id, event_id)
        data.append({"location": loc, "stand_items": items})
    return render_template("events/bulk_count_sheets.html", event=ev, data=data)


@event.route("/events/<int:event_id>/close")
@login_required
def close_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    for el in ev.locations:
        for sheet in el.stand_sheet_items:
            lsi = LocationStandItem.query.filter_by(
                location_id=el.location_id, item_id=sheet.item_id
            ).first()
            if sheet.closing_count == 0:
                if lsi:
                    db.session.delete(lsi)
                continue
            if not lsi:
                lsi = LocationStandItem(
                    location_id=el.location_id, item_id=sheet.item_id
                )
                db.session.add(lsi)
            lsi.expected_count = sheet.closing_count
        TerminalSale.query.filter_by(event_location_id=el.id).delete()
    ev.closed = True
    db.session.commit()
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
            gl_code = item.gl_code_rel.code if item.gl_code_rel else "Unassigned"
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
