import os
from datetime import date
from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    GLCode,
    Item,
    ItemUnit,
    Product,
    ProductRecipeItem,
    Vendor,
    Location,
    User,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    Event,
    EventLocation,
    TerminalSale,
    EventStandSheetItem,
)
from app.utils.backup import create_backup, restore_backup


def populate_data():
    gl = GLCode(code="6000")
    item = Item(name="BackupItem", base_unit="each")
    unit = ItemUnit(
        item=item,
        name="each",
        factor=1,
        receiving_default=True,
        transfer_default=True,
    )
    vendor = Vendor(first_name="Back", last_name="Vendor")
    location = Location(name="BackupLoc")
    user = User(email="backup@example.com", password=generate_password_hash("pass"), active=True)
    db.session.add_all([gl, item, unit, vendor, location, user])
    db.session.commit()

    product = Product(name="BackupProduct", price=1.0, cost=0.5, gl_code="6000")
    recipe = ProductRecipeItem(
        product=product,
        item=item,
        unit=unit,
        quantity=1,
        countable=True,
    )
    po = PurchaseOrder(
        vendor_id=vendor.id,
        user_id=user.id,
        order_date=date(2023, 1, 1),
        expected_date=date(2023, 1, 2),
        delivery_charge=0,
    )
    poi = PurchaseOrderItem(purchase_order=po, item=item, unit=unit, quantity=1)
    invoice = PurchaseInvoice(
        purchase_order=po,
        user_id=user.id,
        location=location,
        received_date=date(2023, 1, 3),
        invoice_number="VN001",
        gst=0.1,
        pst=0.2,
        delivery_charge=1.0,
    )
    pii = PurchaseInvoiceItem(
        invoice=invoice,
        item=item,
        unit=unit,
        item_name=item.name,
        unit_name=unit.name,
        quantity=1,
        cost=2.0,
    )
    event = Event(name="BackupEvent", start_date=date(2023, 2, 1), end_date=date(2023, 2, 2))
    event_loc = EventLocation(event=event, location=location)
    sale = TerminalSale(event_location=event_loc, product=product, quantity=5)
    stand_item = EventStandSheetItem(event_location=event_loc, item=item, opening_count=0, closing_count=0)

    db.session.add_all([
        gl,
        item,
        unit,
        product,
        recipe,
        vendor,
        location,
        user,
        po,
        poi,
        invoice,
        pii,
        event,
        event_loc,
        sale,
        stand_item,
    ])
    db.session.commit()

    models = [
        GLCode,
        Item,
        ItemUnit,
        Product,
        ProductRecipeItem,
        Vendor,
        Location,
        User,
        PurchaseOrder,
        PurchaseOrderItem,
        PurchaseInvoice,
        PurchaseInvoiceItem,
        Event,
        EventLocation,
        TerminalSale,
        EventStandSheetItem,
    ]
    return {m: m.query.count() for m in models}, models


def test_backup_and_restore(app):
    with app.app_context():
        counts, models = populate_data()
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "", 1)
        inode_before = os.stat(db_path).st_ino

        filename = create_backup()
        backup_path = os.path.join(app.config["BACKUP_FOLDER"], filename)
        assert os.path.exists(backup_path)

        for m in models:
            m.query.delete()
        db.session.commit()

        restore_backup(backup_path)

        # Ensure the database file was not replaced during restore
        assert os.stat(db_path).st_ino == inode_before

        for m, count in counts.items():
            assert m.query.count() == count
