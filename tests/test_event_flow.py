from werkzeug.security import generate_password_hash
from app import db
from app.models import (User, Location, Item, ItemUnit, Product, ProductRecipeItem,
                       LocationStandItem, Event, EventLocation, TerminalSale, EventStandSheetItem)
from tests.test_user_flows import login


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
            LocationStandItem(location_id=loc.id, item_id=item.id, expected_count=10)
        )
        db.session.add(
            ProductRecipeItem(
                product_id=product.id, item_id=item.id, quantity=1, countable=True
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
        el = EventLocation.query.filter_by(event_id=eid, location_id=loc_id).first()
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

    with client:
        login(client, email, "pass")
        client.get(f"/events/{eid}/close", follow_redirects=True)

    with app.app_context():
        lsi = LocationStandItem.query.filter_by(location_id=loc_id).first()
        assert lsi.expected_count == 0
        assert TerminalSale.query.filter_by(event_location_id=elid).count() == 0


def test_bulk_stand_sheet(client, app):
    email, loc_id, prod_id, item_id = setup_event_env(app)
    with app.app_context():
        loc2 = Location(name="EventLoc2")
        db.session.add(loc2)
        db.session.commit()
        LocationStandItem(
            location_id=loc2.id, item_id=Item.query.first().id, expected_count=0
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
        el = EventLocation.query.filter_by(event_id=eid, location_id=loc_id).first()
        elid = el.id

    with client:
        login(client, email, "pass")
        client.post(f"/events/{eid}/locations/{elid}/confirm", follow_redirects=True)
        resp = client.get(f"/events/{eid}/locations/{elid}/sales/add")
        assert resp.status_code == 302
        assert f"/events/{eid}" in resp.headers["Location"]
        resp = client.get(f"/events/{eid}/stand_sheet/{loc_id}")
        assert resp.status_code == 302
        assert f"/events/{eid}" in resp.headers["Location"]


def test_save_stand_sheet(client, app):
    email, loc_id, prod_id, item_id = setup_event_env(app)
    with client:
        login(client, email, 'pass')
        client.post('/events/create', data={
            'name': 'SheetEvent',
            'start_date': '2023-03-01',
            'end_date': '2023-03-02'
        }, follow_redirects=True)

    with app.app_context():
        ev = Event.query.filter_by(name='SheetEvent').first()
        eid = ev.id

    with client:
        login(client, email, 'pass')
        client.post(f'/events/{eid}/add_location', data={'location_id': loc_id}, follow_redirects=True)

    with client:
        login(client, email, 'pass')
        client.post(f'/events/{eid}/stand_sheet/{loc_id}', data={
            f'open_{item_id}': 5,
            f'in_{item_id}': 2,
            f'out_{item_id}': 1,
            f'eaten_{item_id}': 1,
            f'spoiled_{item_id}': 0,
            f'close_{item_id}': 3
        }, follow_redirects=True)

    with app.app_context():
        el = EventLocation.query.filter_by(event_id=eid, location_id=loc_id).first()
        sheet = EventStandSheetItem.query.filter_by(event_location_id=el.id, item_id=item_id).first()
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
        login(client, email, 'pass')
        client.post('/events/create', data={
            'name': 'PrefillEvent',
            'start_date': '2023-04-01',
            'end_date': '2023-04-02'
        }, follow_redirects=True)

    with app.app_context():
        ev = Event.query.filter_by(name='PrefillEvent').first()
        eid = ev.id

    with client:
        login(client, email, 'pass')
        client.post(f'/events/{eid}/add_location', data={'location_id': loc_id}, follow_redirects=True)

    with app.app_context():
        el = EventLocation.query.filter_by(event_id=eid, location_id=loc_id).first()
        elid = el.id

    with client:
        login(client, email, 'pass')
        client.post(
            f'/events/{eid}/locations/{elid}/sales/add',
            data={f'qty_{prod_id}': 7},
            follow_redirects=True,
        )
        resp = client.get(f'/events/{eid}/locations/{elid}/sales/add')
        assert resp.status_code == 200
        assert b'value="7"' in resp.data or b'value="7.0"' in resp.data
