from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    GLCode,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemArchive,
    User,
    Vendor,
)
from tests.utils import login


def setup_purchase(app):
    with app.app_context():
        user = User(
            email="buyer@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        vendor = Vendor(first_name="Vend", last_name="Or")
        item = Item(name="Part", base_unit="each")
        unit = ItemUnit(
            item=item,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        location = Location(name="Main")
        db.session.add_all([user, vendor, item, unit, location])
        db.session.commit()
        lsi = LocationStandItem(
            location_id=location.id, item_id=item.id, expected_count=0
        )
        db.session.add(lsi)
        db.session.commit()
        return user.email, vendor.id, item.id, location.id, unit.id


def setup_purchase_with_case(app):
    """Setup purchase scenario with an additional case unit."""
    with app.app_context():
        user = User(
            email="casebuyer@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        vendor = Vendor(first_name="Vend", last_name="Or")
        item = Item(name="CaseItem", base_unit="each")
        each_unit = ItemUnit(
            item=item,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        case_unit = ItemUnit(item=item, name="case", factor=24)
        location = Location(name="Main")
        db.session.add_all(
            [user, vendor, item, each_unit, case_unit, location]
        )
        db.session.commit()
        lsi = LocationStandItem(
            location_id=location.id, item_id=item.id, expected_count=0
        )
        db.session.add(lsi)
        db.session.commit()
        return user.email, vendor.id, item.id, location.id, case_unit.id


def test_purchase_and_receive(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, "pass")
        resp = client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-01-01",
                "expected_date": "2023-01-05",
                "delivery_charge": 2,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        po = PurchaseOrder.query.first()
        assert po is not None
        po_id = po.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-01-04",
                "gst": 0.25,
                "pst": 0.35,
                "delivery_charge": 2,
                "location_id": location_id,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
                "items-0-cost": 2.5,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.quantity == 3
        assert item.cost == 2.5
        lsi = LocationStandItem.query.filter_by(
            location_id=location_id, item_id=item_id
        ).first()
        assert lsi.expected_count == 3
        assert (
            PurchaseOrderItemArchive.query.filter_by(
                purchase_order_id=po_id
            ).count()
            == 1
        )


def test_item_cost_visible_on_items_page(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-01-01",
                "expected_date": "2023-01-05",
                "delivery_charge": 2,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po_id = PurchaseOrder.query.first().id

    with client:
        login(client, email, "pass")
        client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-01-04",
                "gst": 0.25,
                "pst": 0.35,
                "delivery_charge": 2,
                "location_id": location_id,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
                "items-0-cost": 2.5,
            },
            follow_redirects=True,
        )

        resp = client.get("/items")
        assert f"{2.5:.6f} / each" in resp.get_data(as_text=True)


def test_purchase_order_multiple_items(client, app):
    with app.app_context():
        user = User(
            email="multi@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        vendor = Vendor(first_name="Multi", last_name="Vendor")
        item1 = Item(name="PartA", base_unit="each")
        item2 = Item(name="PartB", base_unit="each")
        loc = Location(name="Main")
        db.session.add_all([user, vendor, item1, item2, loc])
        db.session.commit()
        iu1 = ItemUnit(
            item_id=item1.id,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        iu2 = ItemUnit(
            item_id=item2.id,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        db.session.add_all(
            [
                iu1,
                iu2,
                LocationStandItem(
                    location_id=loc.id, item_id=item1.id, expected_count=0
                ),
                LocationStandItem(
                    location_id=loc.id, item_id=item2.id, expected_count=0
                ),
            ]
        )
        db.session.commit()
        vendor_id = vendor.id
        item1_id = item1.id
        item2_id = item2.id
        unit1_id = iu1.id
        unit2_id = iu2.id

    with client:
        login(client, "multi@example.com", "pass")
        resp = client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-02-01",
                "expected_date": "2023-02-05",
                "items-0-item": item1_id,
                "items-0-unit": unit1_id,
                "items-0-quantity": 4,
                "items-1-item": item2_id,
                "items-1-unit": unit2_id,
                "items-1-quantity": 6,
            },
            follow_redirects=True,
        )
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
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-03-01",
                "expected_date": "2023-03-05",
                "delivery_charge": 5.5,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id
        assert po.delivery_charge == 5.5

    with client:
        login(client, email, "pass")
        resp = client.get(f"/purchase_orders/{po_id}/receive")
        assert resp.status_code == 200
        assert b'value="5.50"' in resp.data


def test_receive_prefills_items_and_return(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-04-01",
                "expected_date": "2023-04-05",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        resp = client.get(f"/purchase_orders/{po_id}/receive")
        assert resp.status_code == 200
        assert b'name="items-0-item"' in resp.data

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-04-06",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": -3,
                "items-0-cost": 1.5,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        inv_item = PurchaseInvoiceItem.query.first()
        assert inv_item.cost == 1.5
        assert inv_item.quantity == -3
        assert inv_item.unit_id == unit_id
        assert inv_item.line_total == -4.5
        invoice = PurchaseInvoice.query.first()
        assert invoice.total == -4.5


def test_edit_purchase_order_updates(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-05-01",
                "expected_date": "2023-05-05",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/edit/{po_id}",
            data={
                "vendor": vendor_id,
                "order_date": "2023-05-01",
                "expected_date": "2023-05-06",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 5,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        poi = PurchaseOrderItem.query.filter_by(
            purchase_order_id=po_id
        ).first()
        assert poi.quantity == 5


def test_invoice_moves_and_reverse(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)
    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-06-01",
                "expected_date": "2023-06-05",
                "delivery_charge": 2,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-06-06",
                "location_id": location_id,
                "gst": 0.25,
                "pst": 0.35,
                "delivery_charge": 2,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 3,
                "items-0-cost": 2.5,
            },
            follow_redirects=True,
        )

    with app.app_context():
        inv = PurchaseInvoice.query.first()
        assert round(inv.total, 2) == 10.10
        assert db.session.get(PurchaseOrder, po_id).received
        inv_id = inv.id

    with client:
        login(client, email, "pass")
        resp = client.get("/purchase_orders")
        assert f">{po_id}<".encode() not in resp.data
        resp = client.get("/purchase_invoices")
        assert str(inv_id).encode() in resp.data
        assert b"Main" in resp.data

    with client:
        login(client, email, "pass")
        client.get(
            f"/purchase_invoices/{inv_id}/reverse", follow_redirects=True
        )

    with app.app_context():
        assert PurchaseInvoice.query.get(inv_id) is None
        assert not db.session.get(PurchaseOrder, po_id).received
        item = db.session.get(Item, item_id)
        assert item.quantity == 0
        assert item.cost == 0
        lsi = LocationStandItem.query.filter_by(
            location_id=location_id, item_id=item_id
        ).first()
        assert lsi.expected_count == 0


def test_receive_invoice_base_unit_cost(client, app):
    """Receiving items in cases should update item cost per base unit."""
    email, vendor_id, item_id, location_id, case_unit_id = (
        setup_purchase_with_case(app)
    )

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-07-01",
                "expected_date": "2023-07-05",
                "items-0-item": item_id,
                "items-0-unit": case_unit_id,
                "items-0-quantity": 1,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-07-06",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": case_unit_id,
                "items-0-quantity": 1,
                "items-0-cost": 24,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.quantity == 24
        assert item.cost == 1
        lsi = LocationStandItem.query.filter_by(
            location_id=location_id, item_id=item_id
        ).first()
        assert lsi.expected_count == 24


def test_receive_invoice_missing_unit_defaults(client, app):
    """Omitting unit should use receiving default factor."""
    email, vendor_id, item_id, location_id, case_unit_id = (
        setup_purchase_with_case(app)
    )
    # Make case unit the receiving default
    with app.app_context():
        case_unit = db.session.get(ItemUnit, case_unit_id)
        each_unit = ItemUnit.query.filter_by(item_id=item_id, name="each").first()
        each_unit.receiving_default = False
        case_unit.receiving_default = True
        db.session.commit()

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-08-01",
                "expected_date": "2023-08-05",
                "items-0-item": item_id,
                "items-0-unit": case_unit_id,
                "items-0-quantity": 1,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-08-06",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                # intentionally omit unit
                "items-0-quantity": 1,
                "items-0-cost": 24,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.quantity == 24
        assert item.cost == 1

def test_item_cost_is_average(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-07-10",
                "expected_date": "2023-07-15",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        po1 = PurchaseOrder.query.first()
        po1_id = po1.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po1_id}/receive",
            data={
                "received_date": "2023-07-16",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
                "items-0-cost": 2,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with client:
        login(client, email, "pass")
        resp = client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-07-20",
                "expected_date": "2023-07-25",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        po2 = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
        po2_id = po2.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po2_id}/receive",
            data={
                "received_date": "2023-07-26",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
                "items-0-cost": 4,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.quantity == 4
        assert item.cost == 3


def test_reverse_invoice_restores_average(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)

    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-08-10",
                "expected_date": "2023-08-15",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po1 = PurchaseOrder.query.first()
        po1_id = po1.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/purchase_orders/{po1_id}/receive",
            data={
                "received_date": "2023-08-16",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
                "items-0-cost": 2,
            },
            follow_redirects=True,
        )

    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-08-20",
                "expected_date": "2023-08-25",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po2 = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
        po2_id = po2.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/purchase_orders/{po2_id}/receive",
            data={
                "received_date": "2023-08-26",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
                "items-0-cost": 4,
            },
            follow_redirects=True,
        )

    with app.app_context():
        invoice = PurchaseInvoice.query.order_by(PurchaseInvoice.id.desc()).first()
        inv_id = invoice.id

    with client:
        login(client, email, "pass")
        client.get(f"/purchase_invoices/{inv_id}/reverse", follow_redirects=True)

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.quantity == 2
        assert item.cost == 2


def test_delete_unreceived_purchase_order(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)

    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-08-01",
                "expected_date": "2023-08-05",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/purchase_orders/{po_id}/delete", follow_redirects=True
        )
        assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(PurchaseOrder, po_id) is None
        assert (
            PurchaseOrderItem.query.filter_by(purchase_order_id=po_id).count()
            == 0
        )


def test_invoice_retains_item_and_unit_names_after_unit_removed(client, app):
    email, vendor_id, item_id, location_id, unit_id = setup_purchase(app)

    with client:
        login(client, email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-09-01",
                "expected_date": "2023-09-05",
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po = PurchaseOrder.query.first()
        po_id = po.id

    with client:
        login(client, email, "pass")
        client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-09-06",
                "location_id": location_id,
                "gst": 0,
                "pst": 0,
                "delivery_charge": 0,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 2,
                "items-0-cost": 1.5,
            },
            follow_redirects=True,
        )

    with app.app_context():
        invoice = PurchaseInvoice.query.first()
        inv_id = invoice.id

    # Remove the unit after the invoice is recorded
    with app.app_context():
        db.session.delete(db.session.get(ItemUnit, unit_id))
        db.session.commit()

    with app.app_context():
        inv_item = PurchaseInvoiceItem.query.filter_by(
            invoice_id=inv_id
        ).first()
        assert inv_item.item is not None
        assert inv_item.unit is None
        assert inv_item.item_name == "Part"
        assert inv_item.unit_name == "each"


def test_purchase_invoice_gl_report(client, app):
    """Report should summarize totals per GL code including taxes and delivery."""
    with app.app_context():
        user = User(
            email="glrep@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        vendor = Vendor(first_name="Vend", last_name="Or")
        gl1 = GLCode(code="5100")
        gl2 = GLCode(code="5200")
        item1 = Item(name="PartA", base_unit="each", purchase_gl_code=gl1)
        item2 = Item(name="PartB", base_unit="each", purchase_gl_code=gl2)
        unit1 = ItemUnit(
            item=item1,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        unit2 = ItemUnit(
            item=item2,
            name="each",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        loc = Location(name="Main")
        db.session.add_all(
            [user, vendor, gl1, gl2, item1, item2, unit1, unit2, loc]
        )
        db.session.commit()
        db.session.add_all(
            [
                LocationStandItem(
                    location_id=loc.id, item_id=item1.id, expected_count=0
                ),
                LocationStandItem(
                    location_id=loc.id, item_id=item2.id, expected_count=0
                ),
            ]
        )
        db.session.commit()
        user_email = user.email
        vendor_id = vendor.id
        item1_id = item1.id
        item2_id = item2.id
        unit1_id = unit1.id
        unit2_id = unit2.id
        location_id = loc.id

    with client:
        login(client, user_email, "pass")
        client.post(
            "/purchase_orders/create",
            data={
                "vendor": vendor_id,
                "order_date": "2023-10-01",
                "expected_date": "2023-10-05",
                "items-0-item": item1_id,
                "items-0-unit": unit1_id,
                "items-0-quantity": 1,
                "items-1-item": item2_id,
                "items-1-unit": unit2_id,
                "items-1-quantity": 1,
            },
            follow_redirects=True,
        )

    with app.app_context():
        po_id = PurchaseOrder.query.first().id

    with client:
        login(client, user_email, "pass")
        client.post(
            f"/purchase_orders/{po_id}/receive",
            data={
                "received_date": "2023-10-06",
                "location_id": location_id,
                "gst": 1,
                "pst": 2,
                "delivery_charge": 3,
                "items-0-item": item1_id,
                "items-0-unit": unit1_id,
                "items-0-quantity": 1,
                "items-0-cost": 2,
                "items-1-item": item2_id,
                "items-1-unit": unit2_id,
                "items-1-quantity": 1,
                "items-1-cost": 3,
            },
            follow_redirects=True,
        )

    with app.app_context():
        inv_id = PurchaseInvoice.query.first().id

    with client:
        login(client, user_email, "pass")
        resp = client.get(f"/purchase_invoices/{inv_id}/report")
        assert resp.status_code == 200
        assert b"5100" in resp.data
        assert b"5200" in resp.data
        assert b"102702" in resp.data
        assert b"4.00" in resp.data
        assert b"6.00" in resp.data
