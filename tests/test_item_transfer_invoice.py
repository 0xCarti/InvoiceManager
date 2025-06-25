from werkzeug.security import generate_password_hash
from app import db
from app.models import User, Item, ItemUnit, Location, Transfer, TransferItem, Customer, Product, Invoice
from tests.test_user_flows import login


def create_user(app, email='user@example.com'):
    with app.app_context():
        user = User(email=email, password=generate_password_hash('pass'), active=True)
        db.session.add(user)
        db.session.commit()
        return user.id


def test_item_lifecycle(client, app):
    create_user(app, 'itemuser@example.com')

    with client:
        login(client, 'itemuser@example.com', 'pass')
        resp = client.post('/items/add', data={
            'name': 'Widget',
            'base_unit': 'each',
            'units-0-name': 'each',
            'units-0-factor': 1,
            'units-0-receiving_default': 'y',
            'units-0-transfer_default': 'y'
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        item = Item.query.filter_by(name='Widget').first()
        assert item is not None
        item_id = item.id

    with client:
        login(client, 'itemuser@example.com', 'pass')
        resp = client.post(f'/items/edit/{item_id}', data={
            'name': 'Gadget',
            'base_unit': 'each',
            'units-0-name': 'each',
            'units-0-factor': 1,
            'units-0-receiving_default': 'y',
            'units-0-transfer_default': 'y'
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        updated = db.session.get(Item, item_id)
        assert updated.name == 'Gadget'

    with client:
        login(client, 'itemuser@example.com', 'pass')
        resp = client.post(f'/items/delete/{item_id}', follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Item, item_id) is None


def test_transfer_flow(client, app):
    user_id = create_user(app, 'transfer@example.com')
    with app.app_context():
        loc1 = Location(name='A')
        loc2 = Location(name='B')
        item = Item(name='Thing', base_unit='each')
        db.session.add_all([loc1, loc2, item])
        db.session.commit()
        unit = ItemUnit(item_id=item.id, name='each', factor=1, receiving_default=True, transfer_default=True)
        db.session.add(unit)
        db.session.commit()
        loc1_id, loc2_id, item_id = loc1.id, loc2.id, item.id
        unit_id = unit.id

    with client:
        login(client, 'transfer@example.com', 'pass')
        resp = client.post('/transfers/add', data={
            'from_location_id': loc1_id,
            'to_location_id': loc2_id,
            'items-0-item': item_id,
            'items-0-unit': unit_id,
            'items-0-quantity': 5
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        transfer = Transfer.query.filter_by(user_id=user_id).first()
        assert transfer is not None
        ti = TransferItem.query.filter_by(transfer_id=transfer.id).first()
        assert ti.item_id == item_id and ti.quantity == 5
        tid = transfer.id

    with client:
        login(client, 'transfer@example.com', 'pass')
        resp = client.get(f'/transfers/complete/{tid}', follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Transfer, tid).completed

    with client:
        login(client, 'transfer@example.com', 'pass')
        resp = client.get(f'/transfers/uncomplete/{tid}', follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        assert not db.session.get(Transfer, tid).completed

    with client:
        login(client, 'transfer@example.com', 'pass')
        resp = client.post(f'/transfers/delete/{tid}', follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Transfer, tid) is None


def test_invoice_creation_total(client, app):
    create_user(app, 'invoice@example.com')
    with app.app_context():
        customer = Customer(first_name='John', last_name='Doe')
        product = Product(name='Widget', price=10.0, cost=5.0)
        db.session.add_all([customer, product])
        db.session.commit()
        cust_id = customer.id

    with client:
        login(client, 'invoice@example.com', 'pass')
        resp = client.post('/create_invoice', data={
            'customer': float(cust_id),
            'products': 'Widget?2??'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invoice created successfully' in resp.data

    with app.app_context():
        invoice = Invoice.query.filter_by(customer_id=cust_id).first()
        assert invoice is not None
        assert len(invoice.products) == 1
        assert invoice.products[0].quantity == 2
        assert round(invoice.total, 2) == 22.4
