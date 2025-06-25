from werkzeug.security import generate_password_hash
from app import db
from app.models import User, Customer, Item, ItemUnit, Location, PurchaseOrder, PurchaseOrderItem, PurchaseInvoice, LocationStandItem
from tests.test_user_flows import login


def setup_purchase(app):
    with app.app_context():
        user = User(email='buyer@example.com', password=generate_password_hash('pass'), active=True)
        vendor = Customer(first_name='Vend', last_name='Or')
        item = Item(name='Part', base_unit='each')
        unit = ItemUnit(item=item, name='each', factor=1, receiving_default=True, transfer_default=True)
        location = Location(name='Main')
        db.session.add_all([user, vendor, item, unit, location])
        db.session.commit()
        lsi = LocationStandItem(location_id=location.id, item_id=item.id, expected_count=0)
        db.session.add(lsi)
        db.session.commit()
        return user.email, vendor.id, item.id, location.id, unit.id


def test_purchase_and_receive(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, 'pass')
        resp = client.post('/purchase_orders/create', data={
            'vendor': vendor_id,
            'order_date': '2023-01-01',
            'expected_date': '2023-01-05',
            'delivery_charge': 2,
            'items-0-item': item_id,
            'items-0-unit': unit_id,
            'items-0-quantity': 3
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        po = PurchaseOrder.query.first()
        assert po is not None
        po_id = po.id

    with client:
        login(client, email, 'pass')
        resp = client.post(f'/purchase_orders/{po_id}/receive', data={
            'received_date': '2023-01-04',
            'gst': 0.25,
            'pst': 0.35,
            'delivery_charge': 2,
            'location_id': location_id,
            'items-0-item': item_id,
            'items-0-quantity': 3,
            'items-0-cost': 2.5
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.quantity == 3
        assert item.cost == 2.5
        lsi = LocationStandItem.query.filter_by(location_id=location_id, item_id=item_id).first()
        assert lsi.expected_count == 3


def test_purchase_order_multiple_items(client, app):
    with app.app_context():
        user = User(email='multi@example.com', password=generate_password_hash('pass'), active=True)
        vendor = Customer(first_name='Multi', last_name='Vendor')
        item1 = Item(name='PartA', base_unit='each')
        item2 = Item(name='PartB', base_unit='each')
        loc = Location(name='Main')
        db.session.add_all([user, vendor, item1, item2, loc])
        db.session.commit()
        iu1 = ItemUnit(item_id=item1.id, name='each', factor=1, receiving_default=True, transfer_default=True)
        iu2 = ItemUnit(item_id=item2.id, name='each', factor=1, receiving_default=True, transfer_default=True)
        db.session.add_all([
            iu1,
            iu2,
            LocationStandItem(location_id=loc.id, item_id=item1.id, expected_count=0),
            LocationStandItem(location_id=loc.id, item_id=item2.id, expected_count=0),
        ])
        db.session.commit()
        vendor_id = vendor.id
        item1_id = item1.id
        item2_id = item2.id
        unit1_id = iu1.id
        unit2_id = iu2.id

    with client:
        login(client, 'multi@example.com', 'pass')
        resp = client.post('/purchase_orders/create', data={
            'vendor': vendor_id,
            'order_date': '2023-02-01',
            'expected_date': '2023-02-05',
            'items-0-item': item1_id,
            'items-0-unit': unit1_id,
            'items-0-quantity': 4,
            'items-1-item': item2_id,
            'items-1-unit': unit2_id,
            'items-1-quantity': 6
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        po = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
        assert po.vendor_id == vendor_id
        assert len(po.items) == 2
        ids = {i.item_id for i in po.items}
        assert ids == {item1_id, item2_id}


def test_receive_form_prefills_delivery_charge(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, 'pass')
        client.post('/purchase_orders/create', data={
            'vendor': vendor_id,
            'order_date': '2023-03-01',
            'expected_date': '2023-03-05',
            'delivery_charge': 5.5,
            'items-0-item': item_id,
            'items-0-unit': unit_id,
            'items-0-quantity': 2
        }, follow_redirects=True)

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id
        assert po.delivery_charge == 5.5

    with client:
        login(client, email, 'pass')
        resp = client.get(f'/purchase_orders/{po_id}/receive')
        assert resp.status_code == 200
        assert b'value="5.50"' in resp.data
