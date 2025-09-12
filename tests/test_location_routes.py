from werkzeug.security import generate_password_hash

from app import db
from app.models import (
    GLCode,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    Product,
    ProductRecipeItem,
    User,
)
from tests.utils import login


def setup_data(app):
    with app.app_context():
        user = User(
            email="loc@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        gl = GLCode.query.first()
        item = Item(
            name="Flour",
            base_unit="gram",
            purchase_gl_code_id=gl.id,
        )
        db.session.add_all([user, item])
        db.session.commit()
        unit = ItemUnit(
            item_id=item.id,
            name="gram",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        product = Product(name="Cake", price=5.0, cost=2.0)
        db.session.add_all([unit, product])
        db.session.commit()
        db.session.add(
            ProductRecipeItem(
                product_id=product.id,
                item_id=item.id,
                unit_id=unit.id,
                quantity=1,
                countable=True,
            )
        )
        db.session.commit()
        return user.email, product.id


def test_location_flow(client, app):
    email, prod_id = setup_data(app)
    with client:
        login(client, email, "pass")
        assert client.get("/locations/add").status_code == 200
        resp = client.post(
            "/locations/add",
            data={"name": "Kitchen", "products": str(prod_id)},
            follow_redirects=True,
        )
        assert resp.status_code == 200
    with app.app_context():
        loc = Location.query.filter_by(name="Kitchen").first()
        assert loc is not None
        lid = loc.id
        assert LocationStandItem.query.filter_by(location_id=lid).count() == 1
        # second product for edit test
        prod2 = Product(name="Pie", price=4.0, cost=2.0)
        db.session.add(prod2)
        db.session.commit()
        db.session.add(
            ProductRecipeItem(
                product_id=prod2.id,
                item_id=Item.query.first().id,
                unit_id=ItemUnit.query.first().id,
                quantity=1,
                countable=True,
            )
        )
        db.session.commit()
        prod2_id = prod2.id
    with client:
        login(client, email, "pass")
        resp = client.get("/locations")
        assert resp.status_code == 200
        resp = client.get(f"/locations/{lid}/stand_sheet")
        assert resp.status_code == 200
        assert b"Location: Kitchen" in resp.data
        # edit to add second product triggers stand item creation
        resp = client.post(
            f"/locations/edit/{lid}",
            data={"name": "Kitchen2", "products": f"{prod_id},{prod2_id}"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        resp = client.post(
            f"/locations/delete/{lid}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert client.get("/locations/edit/999").status_code == 404
        assert client.get("/locations/999/stand_sheet").status_code == 404
        assert client.post("/locations/delete/999").status_code == 404
    with app.app_context():
        loc = db.session.get(Location, lid)
        assert loc.archived


def test_location_filters(client, app):
    email, _ = setup_data(app)
    with app.app_context():
        active = Location(name="ActiveLoc")
        archived_loc = Location(name="OldLoc", archived=True)
        db.session.add_all([active, archived_loc])
        db.session.commit()
    with client:
        login(client, email, "pass")
        resp = client.get("/locations")
        assert b"ActiveLoc" in resp.data
        assert b"OldLoc" not in resp.data

        resp = client.get("/locations", query_string={"archived": "archived"})
        assert b"ActiveLoc" not in resp.data
        assert b"OldLoc" in resp.data

        resp = client.get("/locations", query_string={"archived": "all"})
        assert b"ActiveLoc" in resp.data and b"OldLoc" in resp.data

        resp = client.get(
            "/locations",
            query_string={"name_query": "Old", "match_mode": "contains", "archived": "all"},
        )
        assert b"OldLoc" in resp.data
        assert b"ActiveLoc" not in resp.data


def test_copy_stand_sheet_overwrites_and_supports_multiple_targets(client, app):
    email, prod_id = setup_data(app)
    with app.app_context():
        # second product to show overwrite behaviour
        prod2 = Product(name="Pie", price=4.0, cost=2.0)
        db.session.add(prod2)
        db.session.commit()
        db.session.add(
            ProductRecipeItem(
                product_id=prod2.id,
                item_id=Item.query.first().id,
                unit_id=ItemUnit.query.first().id,
                quantity=1,
                countable=True,
            )
        )
        db.session.commit()
        prod2_id = prod2.id
    with client:
        login(client, email, "pass")
        # Source location with product 1
        client.post(
            "/locations/add",
            data={"name": "Source", "products": str(prod_id)},
            follow_redirects=True,
        )
        # Targets initially with product 2
        client.post(
            "/locations/add",
            data={"name": "Target1", "products": str(prod2_id)},
            follow_redirects=True,
        )
        client.post(
            "/locations/add",
            data={"name": "Target2", "products": str(prod2_id)},
            follow_redirects=True,
        )

    with app.app_context():
        source = Location.query.filter_by(name="Source").first()
        t1 = Location.query.filter_by(name="Target1").first()
        t2 = Location.query.filter_by(name="Target2").first()
        # set expected count on source stand item
        src_item = LocationStandItem.query.filter_by(location_id=source.id).first()
        src_item.expected_count = 5
        db.session.commit()
        src_item_id = src_item.item_id
        source_id = source.id
        t1_id = t1.id
        t2_id = t2.id

    with client:
        login(client, email, "pass")
        resp = client.post(
            f"/locations/{source_id}/copy_items",
            json={"target_ids": [t1_id, t2_id]},
        )
        assert resp.status_code == 200
        assert resp.json["success"]

    with app.app_context():
        for loc_id in (t1_id, t2_id):
            loc = db.session.get(Location, loc_id)
            # products overwritten to match source exactly
            assert [p.id for p in loc.products] == [prod_id]
            stand_items = LocationStandItem.query.filter_by(location_id=loc.id).all()
            assert len(stand_items) == 1
            assert stand_items[0].item_id == src_item_id
            assert stand_items[0].expected_count == 5
