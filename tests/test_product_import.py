import pytest
from app import db
from app.models import Item, Product, ProductRecipeItem
from app.routes.auth_routes import _import_products


def setup_items(app):
    with app.app_context():
        bun = Item(name="Buns", base_unit="each")
        patty = Item(name="Patties", base_unit="each")
        db.session.add_all([bun, patty])
        db.session.commit()


def test_import_products_with_recipe(tmp_path, app):
    csv_path = tmp_path / "prods.csv"
    setup_items(app)
    csv_path.write_text("name,price,cost,gl_code,recipe\nBurger,5.0,2.0,4000,Buns;Patties\n")
    with app.app_context():
        count = _import_products(str(csv_path))
        assert count == 1
        prod = Product.query.filter_by(name="Burger").first()
        assert prod is not None
        assert {ri.item.name for ri in prod.recipe_items} == {"Buns", "Patties"}


def test_import_products_missing_item(tmp_path, app):
    csv_path = tmp_path / "prods.csv"
    with app.app_context():
        db.session.add(Item(name="Buns", base_unit="each"))
        db.session.commit()
    csv_path.write_text("name,price,cost,gl_code,recipe\nBurger,5.0,2.0,4000,Buns;Missing\n")
    with app.app_context():
        with pytest.raises(ValueError):
            _import_products(str(csv_path))
        assert Product.query.count() == 0
