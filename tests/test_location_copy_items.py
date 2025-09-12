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
            email="copy@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        gl = GLCode.query.first()
        item = Item(
            name="Sugar",
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
        product = Product(name="Candy", price=1.0, cost=0.5)
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


def test_copy_location_items(client, app):
    email, prod_id = setup_data(app)
    with client:
        login(client, email, "pass")
        # create source location with product
        resp = client.post(
            "/locations/add",
            data={"name": "Source", "products": str(prod_id)},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # create target location without products
        resp = client.post(
            "/locations/add",
            data={"name": "Target", "products": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            source = Location.query.filter_by(name="Source").first()
            target = Location.query.filter_by(name="Target").first()
            assert source and target
            source_id = source.id
            target_id = target.id
        # copy items
        resp = client.post(
            f"/locations/{source_id}/copy_items",
            json={"target_id": target_id},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        # verify target location now has product and stand item
        with app.app_context():
            refreshed = db.session.get(Location, target_id)
            assert len(refreshed.products) == 1
            assert (
                LocationStandItem.query.filter_by(location_id=target_id).count()
                == 1
            )
