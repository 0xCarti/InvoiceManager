import pytest
from app import db
from app.models import Product, Item, ProductRecipeItem
from app.routes.auth_routes import _import_products


def test_import_products_with_recipe(tmp_path, app):
    csv_path = tmp_path / "prods.csv"
    with app.app_context():
        b = Item(name="Buns", base_unit="each")
        p = Item(name="Patties", base_unit="each")
        db.session.add_all([b, p])
        db.session.commit()

    csv_path.write_text("name,price,cost,gl_code,recipe\nBurger,5,3,4000,Buns:2;Patties:1\n")

    with app.app_context():
        count = _import_products(str(csv_path))
        assert count == 1
        prod = Product.query.filter_by(name="Burger").first()
        assert prod is not None
        items = {ri.item.name for ri in prod.recipe_items}
        assert items == {"Buns", "Patties"}
        qty_map = {ri.item.name: ri.quantity for ri in prod.recipe_items}
        assert qty_map["Buns"] == 2
        assert qty_map["Patties"] == 1


def test_import_products_missing_item(tmp_path, app):
    csv_path = tmp_path / "prods.csv"
    csv_path.write_text("name,price,cost,gl_code,recipe\nBurger,5,3,4000,Missing:1\n")

    with app.app_context():
        with pytest.raises(ValueError):
            _import_products(str(csv_path))
        assert Product.query.count() == 0

