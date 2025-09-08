import json
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
        "level": [1] * 9,
        "page_num": [1] * 9,
        "block_num": [1] * 9,
        "par_num": [1] * 9,
        "line_num": [1] * 9,
        "word_num": list(range(1, 10)),
        "left": [0] * 9,
        "top": [0] * 9,
        "width": [0] * 9,
        "height": [0] * 9,
        "conf": [95] * 9,
        "text": [
            "ScanItem",
            "10",
            "8",
            "2",
            "1",
            "0",
            "0",
            "5",
            "4",
        ],
    }
    monkeypatch.setattr(
        "pytesseract.image_to_data", lambda *_args, **_kwargs: dummy_data
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
            f"open_{item_id}": 8,
            f"in_{item_id}": 2,
            f"out_{item_id}": 1,
            f"eaten_{item_id}": 0,
            f"spoiled_{item_id}": 0,
            f"close_{item_id}": 4,
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
