from werkzeug.security import generate_password_hash
from app import db
from app.models import (User, Location, Item, ItemUnit, Product, ProductRecipeItem,
                       LocationStandItem, Event, EventLocation, TerminalSale)
from tests.test_user_flows import login


def setup_event_env(app):
    with app.app_context():
        user = User(email='event@example.com', password=generate_password_hash('pass'), active=True)
        loc = Location(name='EventLoc')
        item = Item(name='EItem', base_unit='each')
        product = Product(name='EProd', price=1.0, cost=0.5)
        db.session.add_all([user, loc, item, product])
        db.session.commit()
        iu = ItemUnit(item_id=item.id, name='each', factor=1, receiving_default=True, transfer_default=True)
        db.session.add(iu)
        db.session.add(LocationStandItem(location_id=loc.id, item_id=item.id, expected_count=10))
        db.session.add(ProductRecipeItem(product_id=product.id, item_id=item.id, quantity=1, countable=True))
        loc.products.append(product)
        db.session.commit()
        return user.email, loc.id, product.id


def test_event_lifecycle(client, app):
    email, loc_id, prod_id = setup_event_env(app)
    with client:
        login(client, email, 'pass')
        client.post('/events/create', data={
            'name': 'Test Event',
            'start_date': '2023-01-01',
            'end_date': '2023-01-02'
        }, follow_redirects=True)

    with app.app_context():
        ev = Event.query.first()
        assert ev is not None
        eid = ev.id

    with client:
        login(client, email, 'pass')
        client.post(f'/events/{eid}/add_location', data={
            'location_id': loc_id,
        }, follow_redirects=True)

    with app.app_context():
        el = EventLocation.query.filter_by(event_id=eid, location_id=loc_id).first()
        assert el is not None
        elid = el.id

    with client:
        login(client, email, 'pass')
        client.post(f'/events/{eid}/locations/{elid}/sales/add', data={
            f'qty_{prod_id}': 3
        }, follow_redirects=True)

    with app.app_context():
        sale = TerminalSale.query.filter_by(event_location_id=elid).first()
        assert sale is not None and sale.quantity == 3

    with client:
        login(client, email, 'pass')
        client.get(f'/events/{eid}/close', follow_redirects=True)

    with app.app_context():
        lsi = LocationStandItem.query.filter_by(location_id=loc_id).first()
        assert lsi.expected_count == 0
        assert TerminalSale.query.filter_by(event_location_id=elid).count() == 0


def test_bulk_stand_sheet(client, app):
    email, loc_id, prod_id = setup_event_env(app)
    with app.app_context():
        loc2 = Location(name='EventLoc2')
        db.session.add(loc2)
        db.session.commit()
        LocationStandItem(location_id=loc2.id, item_id=Item.query.first().id, expected_count=0)
        loc2.products.append(Product.query.first())
        db.session.commit()
        loc2_id = loc2.id

    with client:
        login(client, email, 'pass')
        client.post('/events/create', data={
            'name': 'BulkEvent',
            'start_date': '2023-02-01',
            'end_date': '2023-02-02'
        }, follow_redirects=True)

    with app.app_context():
        ev = Event.query.filter_by(name='BulkEvent').first()
        eid = ev.id

    with client:
        login(client, email, 'pass')
        client.post(f'/events/{eid}/add_location', data={
            'location_id': loc_id,
        }, follow_redirects=True)
        client.post(f'/events/{eid}/add_location', data={
            'location_id': loc2_id,
        }, follow_redirects=True)
        resp = client.get(f'/events/{eid}/stand_sheets')
        assert resp.status_code == 200
        assert b'EventLoc' in resp.data and b'EventLoc2' in resp.data
