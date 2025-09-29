import os
import time
from datetime import date
from io import BytesIO

from werkzeug.security import generate_password_hash

from app import db
from app.forms import MAX_BACKUP_SIZE
from app.models import (
    ActivityLog,
    Event,
    EventLocation,
    EventStandSheetItem,
    GLCode,
    Item,
    ItemUnit,
    Location,
    Product,
    ProductRecipeItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemArchive,
    TerminalSale,
    User,
    Vendor,
)
from app.utils.activity import flush_activity_logs
from app.utils.backup import create_backup, restore_backup
from tests.utils import login


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
    user = User(
        email="backup@example.com",
        password=generate_password_hash("pass"),
        active=True,
    )
    db.session.add_all([gl, item, unit, vendor, location, user])
    db.session.commit()

    product = Product(
        name="BackupProduct", price=1.0, cost=0.5, gl_code="6000"
    )
    recipe = ProductRecipeItem(
        product=product,
        item=item,
        unit=unit,
        quantity=1,
        countable=True,
    )
    db.session.add_all([product, recipe])

    po = PurchaseOrder(
        vendor_id=vendor.id,
        user_id=user.id,
        order_date=date(2023, 1, 1),
        expected_date=date(2023, 1, 2),
        delivery_charge=0,
    )
    db.session.add(po)
    db.session.flush()

    poi = PurchaseOrderItem(
        purchase_order=po, item=item, unit=unit, quantity=1
    )
    archive = PurchaseOrderItemArchive(
        purchase_order_id=po.id,
        item_id=item.id,
        unit_id=unit.id,
        quantity=1,
    )
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
    event = Event(
        name="BackupEvent",
        start_date=date(2023, 2, 1),
        end_date=date(2023, 2, 2),
        event_type="inventory",
    )
    event_loc = EventLocation(event=event, location=location)
    sale = TerminalSale(event_location=event_loc, product=product, quantity=5)
    stand_item = EventStandSheetItem(
        event_location=event_loc, item=item, opening_count=0, closing_count=0
    )

    db.session.add_all(
        [
            poi,
            archive,
            invoice,
            pii,
            event,
            event_loc,
            sale,
            stand_item,
        ]
    )
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
        PurchaseOrderItemArchive,
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
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace(
            "sqlite:///", "", 1
        )
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


def test_restore_backup_file_rejects_path_traversal(client, app):
    with app.app_context():
        admin = User.query.filter_by(is_admin=True).first()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin.id)
        sess["_fresh"] = True
    resp = client.post("/controlpanel/backups/restore/../../etc/passwd")
    assert resp.status_code == 404


def test_backup_retention(app):
    with app.app_context():
        backups_dir = app.config["BACKUP_FOLDER"]
        for f in os.listdir(backups_dir):
            os.remove(os.path.join(backups_dir, f))
        app.config["MAX_BACKUPS"] = 2
        for _ in range(3):
            create_backup()
            time.sleep(1)
        files = sorted(os.listdir(backups_dir))
        assert len(files) == 2


def test_auto_backup_activity_logging(app):
    with app.app_context():
        backups_dir = app.config["BACKUP_FOLDER"]
        for f in os.listdir(backups_dir):
            os.remove(os.path.join(backups_dir, f))

        ActivityLog.query.delete()
        db.session.commit()

        app.config["MAX_BACKUPS"] = 1

        filename1 = create_backup(initiated_by_system=True)
        flush_activity_logs()

        logs = [log.activity for log in ActivityLog.query.order_by(ActivityLog.id)]
        assert logs[-1] == f"System automatically created backup {filename1}"

        time.sleep(1)
        filename2 = create_backup(initiated_by_system=True)
        flush_activity_logs()

        logs = [log.activity for log in ActivityLog.query.order_by(ActivityLog.id)]
        assert (
            f"System automatically deleted backup {filename1}" in logs
        )
        assert logs[-1] == f"System automatically created backup {filename2}"


def test_restore_backup_route_rejects_large_file(client, app):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")
    with client:
        login(client, admin_email, admin_pass)
        big_content = b"a" * (MAX_BACKUP_SIZE + 1)
        data = {"file": (BytesIO(big_content), "large.db")}
        resp = client.post(
            "/controlpanel/backups/restore",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert b"File is too large." in resp.data


def test_restore_backup_route_rejects_invalid_sqlite(client, app):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")
    with client:
        login(client, admin_email, admin_pass)
        data = {"file": (BytesIO(b"not a sqlite"), "bad.db")}
        resp = client.post(
            "/controlpanel/backups/restore",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert b"Invalid SQLite database." in resp.data
