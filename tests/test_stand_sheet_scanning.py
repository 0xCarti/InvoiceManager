import json
from datetime import date
from io import BytesIO

import qrcode
from PIL import Image
from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    Event,
    EventLocation,
    EventStandSheetItem,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    User,
)
from tests.utils import login


def setup_scan_env(app):
    with app.app_context():
        user = User(
            email="scan@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        loc = Location(name="ScanLoc")
        item = Item(name="ScanItem", base_unit="each")
        db.session.add_all([user, loc, item])
        db.session.commit()
        iu = ItemUnit(
            item_id=item.id,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        db.session.add(iu)
        db.session.add(
            LocationStandItem(
                location_id=loc.id, item_id=item.id, expected_count=10
            )
        )
        db.session.commit()
        return user.email, loc.id, item.id


def test_scan_stand_sheet(client, app, monkeypatch):
    email, loc_id, item_id = setup_scan_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "ScanEvent",
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )
    with app.app_context():
        ev = Event.query.filter_by(name="ScanEvent").first()
        eid = ev.id
    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={"location_id": loc_id},
            follow_redirects=True,
        )
    with app.app_context():
        el = EventLocation.query.filter_by(
            event_id=eid, location_id=loc_id
        ).first()
        assert el is not None

    payload = {"event_id": eid, "location_id": loc_id}
    qr = qrcode.make(json.dumps(payload))
    img = Image.new("RGB", (200, 200), "white")
    img.paste(qr.resize((150, 150)), (25, 25))
    buf = BytesIO()
    img.save(buf, format="PDF")
    buf.seek(0)
    data = {"file": (buf, "sheet.pdf")}

    monkeypatch.setattr(
        "app.routes.event_routes.convert_from_path", lambda *a, **k: [img]
    )
    dummy_data = {
        "text": [
            "ScanItem (each)",
            "10",
            "8",
            "2",
            "1",
            "0",
            "0",
            "4",
            "0",
        ],
        "conf": [95] * 9,
        "line_num": [1] * 9,
        "left": [0, 50, 100, 150, 200, 250, 300, 350, 400],
        "top": [0] * 9,
        "width": [10] * 9,
        "height": [10] * 9,
    }
    monkeypatch.setattr(
        "app.routes.event_routes.read_stand_sheet",
        lambda *_args, **_kwargs: dummy_data,
    )

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/events/scan_stand_sheet",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 302
        review_url = resp.headers["Location"]
        resp = client.get(review_url)
        assert resp.status_code == 200
        form_data = {
            f"open_{eid}_{loc_id}_{item_id}": 8,
            f"in_{eid}_{loc_id}_{item_id}": 2,
            f"out_{eid}_{loc_id}_{item_id}": 1,
            f"eaten_{eid}_{loc_id}_{item_id}": 0,
            f"spoiled_{eid}_{loc_id}_{item_id}": 0,
            f"close_{eid}_{loc_id}_{item_id}": 4,
        }
        resp = client.post(review_url, data=form_data, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        el = EventLocation.query.filter_by(
            event_id=eid, location_id=loc_id
        ).first()
        sheet = EventStandSheetItem.query.filter_by(
            event_location_id=el.id, item_id=item_id
        ).first()
        assert sheet is not None
        assert sheet.opening_count == 8
        assert sheet.transferred_in == 2
        assert sheet.transferred_out == 1
        assert sheet.eaten == 0
        assert sheet.spoiled == 0
        assert sheet.closing_count == 4


def test_parse_scanned_sheet_partial_row(app):
    email, loc_id, item_id = setup_scan_env(app)
    with app.app_context():
        ev = Event(
            name="ParseEvent",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            event_type="inventory",
        )
        db.session.add(ev)
        db.session.commit()
        el = EventLocation(event_id=ev.id, location_id=loc_id)
        db.session.add(el)
        db.session.commit()
        ocr_data = {
            "text": ["ScanItem (each)", "8", "2", "1", "4"],
            "conf": [95] * 5,
            "line_num": [1] * 5,
            "left": [0, 100, 150, 200, 350],
            "top": [0] * 5,
            "width": [10] * 5,
            "height": [10] * 5,
        }
        from app.routes.event_routes import _parse_scanned_sheet

        parsed = _parse_scanned_sheet(ocr_data, el)
        pid = str(item_id)
        assert parsed[pid]["opening_count"] == 8
        assert parsed[pid]["transferred_in"] == 2
        assert parsed[pid]["transferred_out"] == 1
        assert parsed[pid]["eaten"] == 0
        assert parsed[pid]["spoiled"] == 0
        assert parsed[pid]["closing_count"] == 4
        flags = parsed[pid]["flags"]
        assert flags["opening_count"] is False
        assert flags["transferred_in"] is False
        assert flags["transferred_out"] is False
        assert flags["eaten"] is True
        assert flags["spoiled"] is True
        assert flags["closing_count"] is False


def test_parse_scanned_sheet_misaligned_row(app):
    email, loc_id, item_id = setup_scan_env(app)
    with app.app_context():
        ev = Event(
            name="MisalignEvent",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            event_type="inventory",
        )
        db.session.add(ev)
        db.session.commit()
        el = EventLocation(event_id=ev.id, location_id=loc_id)
        db.session.add(el)
        db.session.commit()
        ocr_data = {
            "text": ["ScanItem (each)", "8", "2", "1", "4"],
            "conf": [95] * 5,
            "line_num": [1] * 5,
            "left": [0, 100, 150, 400, 350],
            "top": [0] * 5,
            "width": [10] * 5,
            "height": [10] * 5,
        }
        from app.routes.event_routes import _parse_scanned_sheet

        parsed = _parse_scanned_sheet(ocr_data, el)
        pid = str(item_id)
        assert parsed[pid]["opening_count"] == 8
        assert parsed[pid]["transferred_in"] == 2
        # misaligned value should be ignored
        assert parsed[pid]["transferred_out"] == 0
        assert parsed[pid]["closing_count"] == 4
        flags = parsed[pid]["flags"]
        assert flags["transferred_out"] is True
        assert flags["eaten"] is True
        assert flags["spoiled"] is True
