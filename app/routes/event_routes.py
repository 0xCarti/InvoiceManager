import os
import re
import tempfile
from datetime import datetime

import pytesseract
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError
from PIL import Image
from werkzeug.utils import secure_filename

from app import db
from app.forms import (
    EVENT_TYPES,
    EventForm,
    EventLocationConfirmForm,
    EventLocationForm,
    TerminalSalesUploadForm,
)
from app.models import (
    Event,
    EventLocation,
    EventStandSheetItem,
    Location,
    LocationStandItem,
    Product,
    TerminalSale,
)
from app.utils import decode_qr, generate_qr_code

event = Blueprint("event", __name__)


@event.route("/events")
@login_required
def view_events():
    event_type = request.args.get("type")
    query = Event.query
    if event_type:
        query = query.filter_by(event_type=event_type)
    events = query.all()
    create_form = EventForm()
    return render_template(
        "events/view_events.html",
        events=events,
        event_type=event_type,
        event_types=EVENT_TYPES,
        type_labels=dict(EVENT_TYPES),
        create_form=create_form,
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


@event.route("/events/filter", methods=["POST"])
@login_required
def filter_events_ajax():
    event_type = request.form.get("type")
    query = Event.query
    if event_type:
        query = query.filter_by(event_type=event_type)
    events = query.all()
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
        )
        db.session.add(ev)
        db.session.commit()
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
                        sold_at=datetime.utcnow(),
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
        flash("Stand sheet saved")
        location, stand_items = _get_stand_items(location_id, event_id)

    return render_template(
        "events/stand_sheet.html",
        event=ev,
        location=location,
        stand_items=stand_items,
    )


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
        qr = generate_qr_code({"event_id": event_id, "location_id": loc.id})
        data.append({"location": loc, "stand_items": items, "qr": qr})
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
        data.append({"location": loc, "stand_items": items})
    return render_template(
        "events/bulk_count_sheets.html", event=ev, data=data
    )


def _parse_scanned_sheet(ocr_data, event_location, threshold=80):
    """Return parsed stand sheet data with confidence flags."""
    _, stand_items = _get_stand_items(
        event_location.location_id, event_location.event_id
    )
    item_map = {
        entry["item"].name.lower(): entry["item"] for entry in stand_items
    }
    lines = {}
    for text, conf, line in zip(
        ocr_data.get("text", []),
        ocr_data.get("conf", []),
        ocr_data.get("line_num", []),
    ):
        if text.strip():
            lines.setdefault(line, []).append((text, float(conf)))

    results = {}
    for tokens in lines.values():
        words, confs = zip(*tokens)
        numbers = []
        num_confs = []
        name_tokens = []
        for t, c in zip(words, confs):
            if re.match(r"^-?\d+(?:\.\d+)?$", t):
                numbers.append(t)
                num_confs.append(c)
            else:
                name_tokens.append(t)
        name = " ".join(name_tokens).lower()
        # We expect at least seven numeric fields. Index 6 represents the
        # closing count on the stand sheet.
        if name in item_map and len(numbers) >= 7:
            fields = {
                "opening_count": (float(numbers[1]), num_confs[1] < threshold),
                "transferred_in": (
                    float(numbers[2]),
                    num_confs[2] < threshold,
                ),
                "transferred_out": (
                    float(numbers[3]),
                    num_confs[3] < threshold,
                ),
                "eaten": (float(numbers[4]), num_confs[4] < threshold),
                "spoiled": (float(numbers[5]), num_confs[5] < threshold),
                "closing_count": (float(numbers[6]), num_confs[6] < threshold),
            }
            results[str(item_map[name].id)] = {
                k: v[0] for k, v in fields.items()
            }
            results[str(item_map[name].id)]["flags"] = {
                k: v[1] for k, v in fields.items()
            }
    return results


@event.route("/events/scan_stand_sheet", methods=["GET", "POST"])
@login_required
def scan_stand_sheet():
    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            flash("No file uploaded")
            return redirect(url_for("event.scan_stand_sheet"))

        filename = secure_filename(file.filename or "")
        is_pdf = (
            filename.lower().endswith(".pdf")
            or file.mimetype == "application/pdf"
        )
        suffix = ".pdf" if is_pdf else ".png"

        cleanup_paths = []
        image_paths = []
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            file.save(tmp.name)
            path = tmp.name
            cleanup_paths.append(path)

        if is_pdf:
            try:
                images = convert_from_path(path)
            except PDFInfoNotInstalledError:
                for p in cleanup_paths:
                    os.remove(p)
                flash(
                    "Poppler is required to process PDF stand sheets. Please install poppler-utils."
                )
                return redirect(url_for("event.scan_stand_sheet"))
            for img in images:
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png"
                ) as img_tmp:
                    img.save(img_tmp.name, format="PNG")
                    image_paths.append(img_tmp.name)
                    cleanup_paths.append(img_tmp.name)
        else:
            image_paths.append(path)

        parsed_sheets = []
        for img_path in image_paths:
            meta = decode_qr(img_path)
            event_id = meta.get("event_id")
            location_id = meta.get("location_id")
            if not event_id or not location_id:
                for p in cleanup_paths:
                    os.remove(p)
                flash("Invalid or missing QR code")
                return redirect(url_for("event.scan_stand_sheet"))
            el = EventLocation.query.filter_by(
                event_id=event_id, location_id=location_id
            ).first()
            if not el:
                for p in cleanup_paths:
                    os.remove(p)
                flash("Stand sheet not recognized")
                return redirect(url_for("event.scan_stand_sheet"))
            ocr_data = pytesseract.image_to_data(
                Image.open(img_path), output_type=pytesseract.Output.DICT
            )
            parsed = _parse_scanned_sheet(ocr_data, el)
            parsed_sheets.append(
                {
                    "event_id": event_id,
                    "location_id": location_id,
                    "data": parsed,
                }
            )

        session["scanned_sheets"] = parsed_sheets
        for p in cleanup_paths:
            os.remove(p)
        flash("Review scanned data before saving")
        return redirect(url_for("event.review_scanned_sheet"))
    return render_template("events/scan_stand_sheet.html")


@event.route("/events/scan_stand_sheet/review", methods=["GET", "POST"])
@login_required
def review_scanned_sheet():
    data = session.get("scanned_sheets")
    if not data:
        flash("No scanned data to review")
        return redirect(url_for("event.scan_stand_sheet"))
    if request.method == "POST":
        for sheet_data in data:
            event_id = sheet_data.get("event_id")
            location_id = sheet_data.get("location_id")
            el = EventLocation.query.filter_by(
                event_id=event_id, location_id=location_id
            ).first()
            if el is None:
                continue
            prefix = f"{event_id}_{location_id}"
            for item_id in sheet_data["data"].keys():
                iid = int(item_id)
                sheet = EventStandSheetItem.query.filter_by(
                    event_location_id=el.id, item_id=iid
                ).first()
                if not sheet:
                    sheet = EventStandSheetItem(
                        event_location_id=el.id, item_id=iid
                    )
                    db.session.add(sheet)
                sheet.opening_count = (
                    request.form.get(
                        f"open_{prefix}_{item_id}", type=float, default=0
                    )
                    or 0
                )
                sheet.transferred_in = (
                    request.form.get(
                        f"in_{prefix}_{item_id}", type=float, default=0
                    )
                    or 0
                )
                sheet.transferred_out = (
                    request.form.get(
                        f"out_{prefix}_{item_id}", type=float, default=0
                    )
                    or 0
                )
                sheet.eaten = (
                    request.form.get(
                        f"eaten_{prefix}_{item_id}", type=float, default=0
                    )
                    or 0
                )
                sheet.spoiled = (
                    request.form.get(
                        f"spoiled_{prefix}_{item_id}", type=float, default=0
                    )
                    or 0
                )
                sheet.closing_count = (
                    request.form.get(
                        f"close_{prefix}_{item_id}", type=float, default=0
                    )
                    or 0
                )
        db.session.commit()
        session.pop("scanned_sheets", None)
        flash("Stand sheet imported")
        return redirect(url_for("event.scan_stand_sheet"))

    sheets = []
    for sheet_data in data:
        event_id = sheet_data.get("event_id")
        location_id = sheet_data.get("location_id")
        el = EventLocation.query.filter_by(
            event_id=event_id, location_id=location_id
        ).first()
        if el is None:
            continue
        location, stand_items = _get_stand_items(location_id, event_id)
        sheets.append(
            {
                "event": el.event,
                "location": location,
                "stand_items": stand_items,
                "scanned": sheet_data["data"],
                "prefix": f"{event_id}_{location_id}",
            }
        )
    return render_template("events/review_scanned_sheet.html", sheets=sheets)


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
