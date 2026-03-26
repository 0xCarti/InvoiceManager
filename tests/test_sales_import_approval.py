import json
import os

from app import db
from app.models import (
    Item,
    Location,
    LocationStandItem,
    PosSalesImport,
    PosSalesImportLocation,
    PosSalesImportRow,
    Product,
    ProductRecipeItem,
)
from tests.utils import login


def test_admin_can_approve_sales_import_and_apply_inventory(client, app):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    with app.app_context():
        location = Location(name="North Stand")
        item = Item(name="Bun", base_unit="each", quantity=20.0)
        product = Product(name="Hot Dog", price=7.5, cost=2.0)
        db.session.add_all([location, item, product])
        db.session.flush()

        db.session.add(
            ProductRecipeItem(
                product_id=product.id,
                item_id=item.id,
                quantity=2.0,
                countable=True,
            )
        )
        db.session.add(
            LocationStandItem(
                location_id=location.id,
                item_id=item.id,
                expected_count=20.0,
            )
        )

        sales_import = PosSalesImport(
            source_provider="mailgun",
            message_id="msg-approve-1",
            attachment_filename="sales.xls",
            attachment_sha256="a" * 64,
            status="pending",
        )
        db.session.add(sales_import)
        db.session.flush()

        import_location = PosSalesImportLocation(
            import_id=sales_import.id,
            source_location_name="North Stand",
            normalized_location_name="north_stand",
            location_id=location.id,
            parse_index=0,
        )
        db.session.add(import_location)
        db.session.flush()

        row = PosSalesImportRow(
            import_id=sales_import.id,
            location_import_id=import_location.id,
            source_product_name="Hot Dog",
            normalized_product_name="hot_dog",
            product_id=product.id,
            quantity=3.0,
            parse_index=0,
        )
        db.session.add(row)
        db.session.commit()

        sales_import_id = sales_import.id
        row_id = row.id

    with client:
        login(client, admin_email, admin_pass)
        response = client.post(
            f"/controlpanel/sales-imports/{sales_import_id}",
            data={"action": "approve_import"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Import approved" in response.data

    with app.app_context():
        sales_import = db.session.get(PosSalesImport, sales_import_id)
        row = db.session.get(PosSalesImportRow, row_id)
        record = LocationStandItem.query.filter_by(
            location_id=sales_import.locations[0].location_id,
            item_id=ProductRecipeItem.query.filter_by(product_id=row.product_id).first().item_id,
        ).first()
        item = Item.query.filter_by(name="Bun").first()

        assert sales_import.status == "approved"
        assert sales_import.approved_by is not None
        assert sales_import.approved_at is not None
        assert sales_import.approval_batch_id
        assert row.approval_batch_id == sales_import.approval_batch_id
        assert record is not None
        assert record.expected_count == 14.0
        assert item.quantity == 14.0

        metadata = json.loads(row.approval_metadata)
        assert metadata["approval_batch_id"] == sales_import.approval_batch_id
        assert len(metadata["changes"]) == 1
        change = metadata["changes"][0]
        assert change["expected_count_before"] == 20.0
        assert change["expected_count_after"] == 14.0
        assert change["item_quantity_before"] == 20.0
        assert change["item_quantity_after"] == 14.0
        assert change["consumed_quantity"] == 6.0


def test_sales_import_approval_blocked_for_unresolved_mappings(client, app):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")

    with app.app_context():
        sales_import = PosSalesImport(
            source_provider="mailgun",
            message_id="msg-approve-2",
            attachment_filename="sales.xls",
            attachment_sha256="b" * 64,
            status="pending",
        )
        db.session.add(sales_import)
        db.session.flush()

        import_location = PosSalesImportLocation(
            import_id=sales_import.id,
            source_location_name="Unmapped",
            normalized_location_name="unmapped",
            location_id=None,
            parse_index=0,
        )
        db.session.add(import_location)
        db.session.flush()

        db.session.add(
            PosSalesImportRow(
                import_id=sales_import.id,
                location_import_id=import_location.id,
                source_product_name="Unknown",
                normalized_product_name="unknown",
                product_id=None,
                quantity=1.0,
                parse_index=0,
            )
        )
        db.session.commit()
        sales_import_id = sales_import.id

    with client:
        login(client, admin_email, admin_pass)
        response = client.post(
            f"/controlpanel/sales-imports/{sales_import_id}",
            data={"action": "approve_import"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Approval blocked" in response.data

    with app.app_context():
        sales_import = db.session.get(PosSalesImport, sales_import_id)
        assert sales_import.status in {"pending", "needs_mapping"}
        assert sales_import.approved_at is None
