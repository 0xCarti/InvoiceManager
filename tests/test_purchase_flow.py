from werkzeug.security import generate_password_hash
from app import db
from app.models import User, Customer, Product, PurchaseOrder, PurchaseOrderItem
from tests.test_user_flows import login


def setup_purchase(app):
    with app.app_context():
        user = User(email='buyer@example.com', password=generate_password_hash('pass'), active=True)
        vendor = Customer(first_name='Vend', last_name='Or')
        product = Product(name='Part', price=5.0, cost=1.0)
        db.session.add_all([user, vendor, product])
        db.session.commit()
        return user.email, vendor.id, product.id


def test_purchase_and_receive(client, app):
    email, vendor_id, product_id = setup_purchase(app)
    with client:
        login(client, email, 'pass')
        resp = client.post('/purchase_orders/create', data={
            'vendor': vendor_id,
            'order_date': '2023-01-01',
            'expected_date': '2023-01-05',
            'delivery_charge': 2,
            'items-0-product': product_id,
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
            'items-0-product': product_id,
            'items-0-quantity': 3,
            'items-0-cost': 2.5
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        product = db.session.get(Product, product_id)
        assert product.quantity == 3
        assert product.cost == 2.5


def test_purchase_order_multiple_items(client, app):
    with app.app_context():
        user = User(email='multi@example.com', password=generate_password_hash('pass'), active=True)
        vendor = Customer(first_name='Multi', last_name='Vendor')
        product1 = Product(name='PartA', price=1.0, cost=0.5)
        product2 = Product(name='PartB', price=2.0, cost=0.8)
        db.session.add_all([user, vendor, product1, product2])
        db.session.commit()
        vendor_id = vendor.id
        prod1_id = product1.id
        prod2_id = product2.id

    with client:
        login(client, 'multi@example.com', 'pass')
        resp = client.post('/purchase_orders/create', data={
            'vendor': vendor_id,
            'order_date': '2023-02-01',
            'expected_date': '2023-02-05',
            'items-0-product': prod1_id,
            'items-0-quantity': 4,
            'items-1-product': prod2_id,
            'items-1-quantity': 6
        }, follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        po = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
        assert po.vendor_id == vendor_id
        assert len(po.items) == 2
        ids = {i.product_id for i in po.items}
        assert ids == {prod1_id, prod2_id}
