from werkzeug.security import generate_password_hash

from app import db
from app.models import GLCode, Item, ItemUnit, Product, ProductRecipeItem, User
from tests.utils import login


def setup_data(app):
    with app.app_context():
        user = User(
            email="prodextra@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        item = Item(name="Sugar", base_unit="gram", cost=1.0)
        db.session.add_all([user, item])
        db.session.commit()
        unit = ItemUnit(
            item_id=item.id,
            name="gram",
            factor=1,
            receiving_default=True,
            transfer_default=True,
        )
        db.session.add(unit)
        db.session.commit()
        return user.email, item.id, unit.id


def test_additional_product_routes(client, app):
    email, item_id, unit_id = setup_data(app)
    with client:
        login(client, email, "pass")
        # View and create product form (GET)
        assert client.get("/products").status_code == 200
        assert client.get("/products/create").status_code == 200
        with app.app_context():
            gl_id = GLCode.query.filter_by(code="4000").first().id
        resp = client.post(
            "/products/create",
            data={
                "name": "Candy",
                "price": 2,
                "cost": 1,
                "gl_code_id": gl_id,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 1,
                "items-0-countable": "y",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
    with app.app_context():
        prod = Product.query.filter_by(name="Candy").first()
        assert prod.gl_code == "4000"
        pid = prod.id
        # add second recipe item for append_entry path
        db.session.add(
            ProductRecipeItem(
                product_id=pid,
                item_id=item_id,
                unit_id=unit_id,
                quantity=2,
                countable=True,
            )
        )
        db.session.commit()
    with client:
        login(client, email, "pass")
        # Edit page GET
        assert client.get(f"/products/{pid}/edit").status_code == 200
        assert (
            client.post(
                f"/products/{pid}/edit", data={}, follow_redirects=True
            ).status_code
            == 200
        )
        # Trigger gl_code lookup in edit by posting without gl_code
        resp = client.post(
            f"/products/{pid}/edit",
            data={
                "name": "Candy",
                "price": 3,
                "cost": 1,
                "gl_code_id": gl_id,
                "items-0-item": item_id,
                "items-0-unit": unit_id,
                "items-0-quantity": 1,
                "items-0-countable": "y",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Recipe page GET should append entry for second recipe item
        assert client.get(f"/products/{pid}/recipe").status_code == 200
        # Calculate cost
        resp = client.get(f"/products/{pid}/calculate_cost")
        assert b"cost" in resp.data
        assert client.get("/products/999/calculate_cost").status_code == 404
        # Search products
        resp = client.get("/search_products?query=cand")
        assert b"Candy" in resp.data
        # Delete product
        assert (
            client.post(
                f"/products/{pid}/delete", follow_redirects=True
            ).status_code
            == 200
        )
        # 404 paths
        assert client.get("/products/999/edit").status_code == 404
        assert client.get("/products/999/recipe").status_code == 404


def test_view_products_sales_gl_code_filter(client, app):
    email, item_id, unit_id = setup_data(app)
    with app.app_context():
        gl1 = GLCode.query.filter_by(code="4000").first()
        gl2 = GLCode.query.filter_by(code="5000").first()
        gl1_id, gl2_id = gl1.id, gl2.id
        products = [
            Product(name=f"P{i}", price=1, cost=1, sales_gl_code_id=gl1_id)
            for i in range(21)
        ]
        products.append(
            Product(name="Other", price=1, cost=1, sales_gl_code_id=gl2_id)
        )
        db.session.add_all(products)
        db.session.commit()
    with client:
        login(client, email, "pass")
        resp = client.get(f"/products?sales_gl_code_id={gl1_id}")
        assert resp.status_code == 200
        assert b"P0" in resp.data
        assert b"Other" not in resp.data
        assert f"sales_gl_code_id={gl1_id}".encode() in resp.data
