from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort
from flask_login import login_required

from app import db
from app.activity_logger import log_activity
from app.forms import ProductWithRecipeForm, ProductRecipeForm
from app.models import Product, Item, ItemUnit, ProductRecipeItem, GLCode

product = Blueprint('product', __name__)

@product.route('/products')
@login_required
def view_products():
    """List available products."""
    products = Product.query.all()
    return render_template('products/view_products.html', products=products)


@product.route('/products/create', methods=['GET', 'POST'])
@login_required
def create_product():
    """Add a new product definition."""
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        product = Product(
            name=form.name.data,
            price=form.price.data,
            cost=form.cost.data,  # Save cost
            gl_code=form.gl_code.data,
            gl_code_id=form.gl_code_id.data,
            sales_gl_code_id=form.sales_gl_code.data or None,
        )
        if not product.gl_code and product.gl_code_id:
            gl = db.session.get(GLCode, product.gl_code_id)
            if gl:
                product.gl_code = gl.code
        db.session.add(product)
        db.session.commit()

        for item_form in form.items:
            item_id = item_form.item.data
            unit_id = item_form.unit.data or None
            quantity = item_form.quantity.data
            countable = item_form.countable.data
            if item_id and quantity is not None:
                db.session.add(
                    ProductRecipeItem(
                        product_id=product.id,
                        item_id=item_id,
                        unit_id=unit_id,
                        quantity=quantity,
                        countable=countable,
                    )
                )
        db.session.commit()
        log_activity(f'Created product {product.name}')
        flash('Product created successfully!', 'success')
        return redirect(url_for('product.view_products'))
    return render_template('products/create_product.html', form=form, product_id=None)


@product.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    """Edit product details and recipe."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        product.name = form.name.data
        product.price = form.price.data
        product.cost = form.cost.data or 0.0  # 👈 Update cost
        product.gl_code = form.gl_code.data
        product.gl_code_id = form.gl_code_id.data
        product.sales_gl_code_id = form.sales_gl_code.data or None
        if not product.gl_code and product.gl_code_id:
            gl = db.session.get(GLCode, product.gl_code_id)
            if gl:
                product.gl_code = gl.code

        ProductRecipeItem.query.filter_by(product_id=product.id).delete()
        for item_form in form.items:
            item_id = item_form.item.data
            unit_id = item_form.unit.data or None
            quantity = item_form.quantity.data
            countable = item_form.countable.data
            if item_id and quantity is not None:
                db.session.add(
                    ProductRecipeItem(
                        product_id=product.id,
                        item_id=item_id,
                        unit_id=unit_id,
                        quantity=quantity,
                        countable=countable,
                    )
                )
        db.session.commit()
        log_activity(f'Edited product {product.id}')
        flash('Product updated successfully!', 'success')
        return redirect(url_for('product.view_products'))
    elif request.method == 'GET':
        form.name.data = product.name
        form.price.data = product.price
        form.cost.data = product.cost or 0.0  # 👈 Pre-fill cost
        form.gl_code.data = product.gl_code
        form.gl_code_id.data = product.gl_code_id
        form.sales_gl_code.data = product.sales_gl_code_id
        form.items.min_entries = max(1, len(product.recipe_items))
        item_choices = [(itm.id, itm.name) for itm in Item.query.all()]
        unit_choices = [(u.id, u.name) for u in ItemUnit.query.all()]
        for i, recipe_item in enumerate(product.recipe_items):
            if len(form.items) <= i:
                form.items.append_entry()
                form.items[i].item.choices = item_choices
                form.items[i].unit.choices = unit_choices
            else:
                form.items[i].item.choices = item_choices
                form.items[i].unit.choices = unit_choices
            form.items[i].item.data = recipe_item.item_id
            form.items[i].unit.data = recipe_item.unit_id
            form.items[i].quantity.data = recipe_item.quantity
            form.items[i].countable.data = recipe_item.countable
    else:
        print(form.errors)
        print(form.cost.data)
    return render_template('products/edit_product.html', form=form, product_id=product.id)


@product.route('/products/<int:product_id>/recipe', methods=['GET', 'POST'])
@login_required
def edit_product_recipe(product_id):
    """Edit the recipe for a product."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    form = ProductRecipeForm()
    if form.validate_on_submit():
        ProductRecipeItem.query.filter_by(product_id=product.id).delete()
        items = [key for key in request.form.keys() if key.startswith('items-') and key.endswith('-item')]
        for field in items:
            index = field.split('-')[1]
            item_id = request.form.get(f'items-{index}-item', type=int)
            unit_id = request.form.get(f'items-{index}-unit', type=int)
            quantity = request.form.get(f'items-{index}-quantity', type=float)
            countable = request.form.get(f'items-{index}-countable') == 'y'
            if item_id and quantity is not None:
                db.session.add(ProductRecipeItem(product_id=product.id, item_id=item_id, unit_id=unit_id, quantity=quantity, countable=countable))
        db.session.commit()
        flash('Recipe updated successfully!', 'success')
        return redirect(url_for('product.view_products'))
    elif request.method == 'GET':
        form.items.min_entries = max(1, len(product.recipe_items))
        item_choices = [(itm.id, itm.name) for itm in Item.query.all()]
        unit_choices = [(u.id, u.name) for u in ItemUnit.query.all()]
        for i, recipe_item in enumerate(product.recipe_items):
            if len(form.items) <= i:
                form.items.append_entry()
                form.items[i].item.choices = item_choices
                form.items[i].unit.choices = unit_choices
            else:
                form.items[i].item.choices = item_choices
                form.items[i].unit.choices = unit_choices
            form.items[i].item.data = recipe_item.item_id
            form.items[i].unit.data = recipe_item.unit_id
            form.items[i].quantity.data = recipe_item.quantity
            form.items[i].countable.data = recipe_item.countable
    return render_template('products/edit_product_recipe.html', form=form, product=product)


@product.route('/products/<int:product_id>/calculate_cost')
@login_required
def calculate_product_cost(product_id):
    """Calculate the total recipe cost for a product."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    total = 0.0
    for ri in product.recipe_items:
        item_cost = getattr(ri.item, 'cost', 0.0)
        try:
            qty = float(ri.quantity or 0)
        except (TypeError, ValueError):
            qty = 0
        factor = ri.unit.factor if ri.unit else 1
        total += (item_cost or 0) * qty * factor
    return jsonify({'cost': total})


@product.route('/products/<int:product_id>/delete', methods=['GET'])
@login_required
def delete_product(product_id):
    """Delete a product and its recipe."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    db.session.delete(product)
    db.session.commit()
    log_activity(f'Deleted product {product.id}')
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('product.view_products'))

@product.route('/search_products')
def search_products():
    """Return products matching a search query."""
    # Retrieve query parameter from the URL
    query = request.args.get('query', '').lower()
    # Query the database for products that match the search query
    matched_products = Product.query.filter(Product.name.ilike(f'%{query}%')).all()
    # Include id so that search results can be referenced elsewhere
    product_data = [
        {'id': product.id, 'name': product.name, 'price': product.price}
        for product in matched_products
    ]
    # Return matched product names and prices as JSON
    return jsonify(product_data)
