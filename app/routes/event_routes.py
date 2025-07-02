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
)
from werkzeug.utils import secure_filename
import os
import pandas as pd
import pdfplumber


event = Blueprint("event", __name__)


@event.route("/events")
@login_required
def view_events():
    events = Event.query.all()
    return render_template("events/view_events.html", events=events)


@event.route("/events/create", methods=["GET", "POST"])
@login_required
def create_event():
    form = EventForm()
    if form.validate_on_submit():
        ev = Event(
            name=form.name.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
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
                        sales_by_item[ri.item_id] = (
                            sales_by_item.get(ri.item_id, 0) + sale.quantity * ri.quantity
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
                stand_items.append(
                    {
                        "item": recipe_item.item,
                        "expected": expected,
                        "sales": sales,
                        "sheet": sheet_map.get(recipe_item.item_id),
                    }
                )

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


@event.route("/events/<int:event_id>/close")
@login_required
def close_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    for el in ev.locations:
        lsi = LocationStandItem.query.filter_by(location_id=el.location_id).all()
        for record in lsi:
            record.expected_count = el.closing_count
        TerminalSale.query.filter_by(event_location_id=el.id).delete()
    ev.closed = True
    db.session.commit()
    flash("Event closed")
    return redirect(url_for("event.view_events"))
