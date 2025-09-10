import os
from datetime import datetime, timedelta, date
from io import BytesIO
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
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
    Product,
    ProductRecipeItem,
    TerminalSale,
    User,
)
from tests.utils import login


def setup_upload_env(app):
    with app.app_context():
        user = User(
            email="upload@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        east = Location(name="Popcorn East")
        west = Location(name="Popcorn West")
        prod1 = Product(name="591ml 7-Up", price=1.0, cost=0.5)
        prod2 = Product(name="Butter Topping Large", price=1.0, cost=0.5)
        db.session.add_all([user, east, west, prod1, prod2])
        db.session.commit()
        return user.email, east.id, west.id, prod1.id, prod2.id


def setup_event_env(app):
    with app.app_context():
        user = User(
            email="event@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        loc = Location(name="EventLoc")
        item = Item(name="EItem", base_unit="each")
        product = Product(name="EProd", price=1.0, cost=0.5)
        db.session.add_all([user, loc, item, product])
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
        db.session.add(
            ProductRecipeItem(
                product_id=product.id,
                item_id=item.id,
                unit_id=iu.id,
                quantity=1,
                countable=True,
            )
        )
        loc.products.append(product)
        db.session.commit()
        return user.email, loc.id, product.id, item.id


def test_event_lifecycle(client, app):
    email, loc_id, prod_id, item_id = setup_event_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "Test Event",
                "start_date": "2023-01-01",
                "end_date": "2023-01-02",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.first()
        assert ev is not None
        eid = ev.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={
                "location_id": loc_id,
            },
            follow_redirects=True,
        )

    with app.app_context():
        el = EventLocation.query.filter_by(
            event_id=eid, location_id=loc_id
        ).first()
        assert el is not None
        elid = el.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/locations/{elid}/sales/add",
            data={f"qty_{prod_id}": 3},
            follow_redirects=True,
        )

    with app.app_context():
        sale = TerminalSale.query.filter_by(event_location_id=elid).first()
        assert sale is not None and sale.quantity == 3
        assert sale.sold_at is not None
        assert (datetime.utcnow() - sale.sold_at).total_seconds() < 10

    with client:
        login(client, email, "pass")
        client.get(f"/events/{eid}/close", follow_redirects=True)

    with app.app_context():
        lsi = LocationStandItem.query.filter_by(location_id=loc_id).first()
        assert lsi is None
        assert (
            TerminalSale.query.filter_by(event_location_id=elid).count() == 0
        )


def test_bulk_stand_sheet(client, app):
    email, loc_id, prod_id, item_id = setup_event_env(app)
    with app.app_context():
        loc2 = Location(name="EventLoc2")
        db.session.add(loc2)
        db.session.commit()
        LocationStandItem(
            location_id=loc2.id,
            item_id=Item.query.first().id,
            expected_count=0,
        )
        loc2.products.append(Product.query.first())
        db.session.commit()
        loc2_id = loc2.id

    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "BulkEvent",
                "start_date": "2023-02-01",
                "end_date": "2023-02-02",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.filter_by(name="BulkEvent").first()
        eid = ev.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={
                "location_id": loc_id,
            },
            follow_redirects=True,
        )
        client.post(
            f"/events/{eid}/add_location",
            data={
                "location_id": loc2_id,
            },
            follow_redirects=True,
        )
        resp = client.get(f"/events/{eid}/stand_sheets")
        assert resp.status_code == 200
        assert b"EventLoc" in resp.data and b"EventLoc2" in resp.data


def test_no_sales_after_confirmation(client, app):
    email, loc_id, prod_id, _ = setup_event_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "ConfirmEvent",
                "start_date": "2023-03-01",
                "end_date": "2023-03-02",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.filter_by(name="ConfirmEvent").first()
        eid = ev.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={
                "location_id": loc_id,
            },
            follow_redirects=True,
        )

    with app.app_context():
        el = EventLocation.query.filter_by(
            event_id=eid, location_id=loc_id
        ).first()
        elid = el.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/locations/{elid}/confirm", follow_redirects=True
        )
        resp = client.get(f"/events/{eid}/locations/{elid}/sales/add")
        assert resp.status_code == 302
        assert f"/events/{eid}" in resp.headers["Location"]
        resp = client.get(f"/events/{eid}/stand_sheet/{loc_id}")
        assert resp.status_code == 302
        assert f"/events/{eid}" in resp.headers["Location"]


def test_save_stand_sheet(client, app):
    email, loc_id, prod_id, item_id = setup_event_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "SheetEvent",
                "start_date": "2023-03-01",
                "end_date": "2023-03-02",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.filter_by(name="SheetEvent").first()
        eid = ev.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={"location_id": loc_id},
            follow_redirects=True,
        )

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/stand_sheet/{loc_id}",
            data={
                f"open_{item_id}": 5,
                f"in_{item_id}": 2,
                f"out_{item_id}": 1,
                f"eaten_{item_id}": 1,
                f"spoiled_{item_id}": 0,
                f"close_{item_id}": 3,
            },
            follow_redirects=True,
        )

    with app.app_context():
        el = EventLocation.query.filter_by(
            event_id=eid, location_id=loc_id
        ).first()
        sheet = EventStandSheetItem.query.filter_by(
            event_location_id=el.id, item_id=item_id
        ).first()
        assert sheet is not None
        assert sheet.opening_count == 5
        assert sheet.transferred_in == 2
        assert sheet.transferred_out == 1
        assert sheet.eaten == 1
        assert sheet.spoiled == 0
        assert sheet.closing_count == 3


def test_terminal_sales_prefill(client, app):
    email, loc_id, prod_id, _ = setup_event_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "PrefillEvent",
                "start_date": "2023-04-01",
                "end_date": "2023-04-02",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.filter_by(name="PrefillEvent").first()
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
        elid = el.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/locations/{elid}/sales/add",
            data={f"qty_{prod_id}": 7},
            follow_redirects=True,
        )
        resp = client.get(f"/events/{eid}/locations/{elid}/sales/add")
        assert resp.status_code == 200
        assert b'value="7"' in resp.data or b'value="7.0"' in resp.data


def test_upload_sales_xls(client, app):
    email, east_id, west_id, prod1_id, prod2_id = setup_upload_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "UploadXLS",
                "start_date": "2025-06-20",
                "end_date": "2025-06-21",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.filter_by(name="UploadXLS").first()
        eid = ev.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={"location_id": east_id},
            follow_redirects=True,
        )
        client.post(
            f"/events/{eid}/add_location",
            data={"location_id": west_id},
            follow_redirects=True,
        )

    wb = Workbook()
    ws = wb.active
    ws.append(["Popcorn East"])
    ws.append([1, "591ml 7-Up", None, None, 7])
    ws.append(["Popcorn West"])
    ws.append([1, "591ml 7-Up", None, None, 2])
    ws.append(["Pizza"])
    ws.append([1, "591ml 7-Up", None, None, 5])
    ws.append(["Grand Valley Dog"])
    ws.append([1, "591ml 7-Up", None, None, 3])
    tmp = BytesIO()
    wb.save(tmp)
    tmp.seek(0)
    data = {"file": (tmp, "sales.xls")}
    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/events/{eid}/sales/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Pizza" in resp.data and b"Grand Valley Dog" in resp.data

    with app.app_context():
        east_el = EventLocation.query.filter_by(
            event_id=eid, location_id=east_id
        ).first()
        west_el = EventLocation.query.filter_by(
            event_id=eid, location_id=west_id
        ).first()
        prod1 = db.session.get(Product, prod1_id)
        sale_e = TerminalSale.query.filter_by(
            event_location_id=east_el.id, product_id=prod1.id
        ).first()
        sale_w = TerminalSale.query.filter_by(
            event_location_id=west_el.id, product_id=prod1.id
        ).first()
        assert sale_e and sale_e.quantity == 7 and sale_e.sold_at
        assert sale_w and sale_w.quantity == 2 and sale_w.sold_at


def test_upload_sales_pdf(client, app):
    email, east_id, west_id, prod1_id, prod2_id = setup_upload_env(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/events/create",
            data={
                "name": "UploadPDF",
                "start_date": "2025-06-20",
                "end_date": "2025-06-21",
                "event_type": "inventory",
            },
            follow_redirects=True,
        )

    with app.app_context():
        ev = Event.query.filter_by(name="UploadPDF").first()
        eid = ev.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/events/{eid}/add_location",
            data={"location_id": east_id},
            follow_redirects=True,
        )
        client.post(
            f"/events/{eid}/add_location",
            data={"location_id": west_id},
            follow_redirects=True,
        )

    pdf_buf = BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=letter)
    lines = [
        "Popcorn East",
        "1 591ml 7-Up 4.00 3 7",
        "Popcorn West",
        "1 591ml 7-Up 4.00 3 2",
        "Pizza",
        "1 591ml 7-Up 4.00 3 5",
        "Grand Valley Dog",
        "1 591ml 7-Up 4.00 3 3",
    ]
    y = 750
    for line in lines:
        c.drawString(100, y, line)
        y -= 20
    c.showPage()
    c.save()
    pdf_buf.seek(0)
    data = {"file": (pdf_buf, "sales.pdf")}
    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/events/{eid}/sales/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Pizza" in resp.data and b"Grand Valley Dog" in resp.data

    with app.app_context():
        east_el = EventLocation.query.filter_by(
            event_id=eid, location_id=east_id
        ).first()
        west_el = EventLocation.query.filter_by(
            event_id=eid, location_id=west_id
        ).first()
        prod1 = db.session.get(Product, prod1_id)
        sale_e = TerminalSale.query.filter_by(
            event_location_id=east_el.id, product_id=prod1.id
        ).first()
        sale_w = TerminalSale.query.filter_by(
            event_location_id=west_el.id, product_id=prod1.id
        ).first()
        assert sale_e and sale_e.quantity == 7 and sale_e.sold_at
        assert sale_w and sale_w.quantity == 2 and sale_w.sold_at


def test_terminal_sale_last_sale(app):
    email, loc_id, prod_id, _ = setup_event_env(app)
    with app.app_context():
        loc = db.session.get(Location, loc_id)
        prod = db.session.get(Product, prod_id)
        event1 = Event(
            name="TS1",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 1, 2),
            event_type="inventory",
        )
        el1 = EventLocation(event=event1, location=loc)
        sale1 = TerminalSale(
            event_location=el1,
            product=prod,
            quantity=1,
            sold_at=datetime.utcnow() - timedelta(days=1),
        )
        event2 = Event(
            name="TS2",
            start_date=date(2023, 1, 3),
            end_date=date(2023, 1, 4),
            event_type="inventory",
        )
        el2 = EventLocation(event=event2, location=loc)
        sale2 = TerminalSale(
            event_location=el2,
            product=prod,
            quantity=2,
        )
        db.session.add_all([event1, el1, sale1, event2, el2, sale2])
        db.session.commit()

        last_sale = (
            TerminalSale.query.filter_by(product_id=prod.id)
            .order_by(TerminalSale.sold_at.desc())
            .first()
        )
        assert last_sale.quantity == 2
