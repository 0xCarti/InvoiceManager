from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased, selectinload

from app import db
from app.forms import (
    BulkProductCostForm,
    DeleteForm,
    QuickProductForm,
    ProductRecipeForm,
    ProductWithRecipeForm,
)
from app.models import (
    GLCode,
    Item,
    ItemUnit,
    Product,
    ProductRecipeItem,
    Customer,
    Invoice,
    InvoiceProduct,
    TerminalSale,
)
from app.utils.activity import log_activity
from app.utils.numeric import coerce_float
from app.utils.pagination import build_pagination_args, get_per_page

product = Blueprint("product", __name__)


@product.route("/products")
@login_required
def view_products():
    """List available products."""
    if request.args.get("reset"):
        session.pop("product_filters", None)
        return redirect(url_for("product.view_products"))

    if not request.args and "product_filters" in session:
        return redirect(url_for("product.view_products", **session["product_filters"]))

    if request.args:
        session["product_filters"] = request.args.to_dict(flat=False)

    delete_form = DeleteForm()
    bulk_cost_form = BulkProductCostForm()
    create_form = ProductWithRecipeForm()
    page = request.args.get("page", 1, type=int)
    per_page = get_per_page()
    name_query = request.args.get("name_query", "")
    match_mode = request.args.get("match_mode", "contains")
    sales_gl_code_ids = [
        int(x) for x in request.args.getlist("sales_gl_code_id") if x.isdigit()
    ]
    customer_id = request.args.get("customer_id", type=int)
    cost_min = coerce_float(request.args.get("cost_min"))
    cost_max = coerce_float(request.args.get("cost_max"))
    price_min = coerce_float(request.args.get("price_min"))
    price_max = coerce_float(request.args.get("price_max"))
    last_sold_before_str = request.args.get("last_sold_before")
    include_unsold = request.args.get("include_unsold") in [
        "1",
        "true",
        "True",
        "yes",
        "on",
    ]
    last_sold_before = None
    if last_sold_before_str:
        try:
            last_sold_before = datetime.strptime(last_sold_before_str, "%Y-%m-%d")
        except ValueError:
            flash(
                "Invalid date format for last_sold_before. Use YYYY-MM-DD.",
                "error",
            )
            return redirect(url_for("product.view_products"))

    query = Product.query
    if name_query:
        if match_mode == "exact":
            query = query.filter(Product.name == name_query)
        elif match_mode == "startswith":
            query = query.filter(Product.name.like(f"{name_query}%"))
        elif match_mode == "contains":
            query = query.filter(Product.name.like(f"%{name_query}%"))
        elif match_mode == "not_contains":
            query = query.filter(Product.name.notlike(f"%{name_query}%"))
        else:
            query = query.filter(Product.name.like(f"%{name_query}%"))

    if sales_gl_code_ids:
        query = query.filter(Product.sales_gl_code_id.in_(sales_gl_code_ids))
    if customer_id:
        invoice_alias = aliased(Invoice)
        query = (
            query.join(InvoiceProduct, Product.invoice_products)
            .join(invoice_alias, InvoiceProduct.invoice_id == invoice_alias.id)
            .filter(invoice_alias.customer_id == customer_id)
            .distinct()
        )

    if cost_min is not None and cost_max is not None and cost_min > cost_max:
        flash("Invalid cost range: min cannot be greater than max.", "error")
        session.pop("product_filters", None)
        return redirect(url_for("product.view_products"))
    if (
        price_min is not None
        and price_max is not None
        and price_min > price_max
    ):
        flash("Invalid price range: min cannot be greater than max.", "error")
        session.pop("product_filters", None)
        return redirect(url_for("product.view_products"))
    if cost_min is not None:
        query = query.filter(Product.cost >= cost_min)
    if cost_max is not None:
        query = query.filter(Product.cost <= cost_max)
    if price_min is not None:
        query = query.filter(Product.price >= price_min)
    if price_max is not None:
        query = query.filter(Product.price <= price_max)
    last_sold_expr = func.max(
        func.coalesce(Invoice.date_created, TerminalSale.sold_at)
    )
    query = (
        query.outerjoin(InvoiceProduct, Product.invoice_products)
        .outerjoin(Invoice, InvoiceProduct.invoice_id == Invoice.id)
        .outerjoin(TerminalSale, Product.id == TerminalSale.product_id)
        .group_by(Product.id)
    )
    if last_sold_before:
        if include_unsold:
            query = query.having(
                or_(
                    last_sold_expr < last_sold_before,
                    last_sold_expr.is_(None),
                )
            )
        else:
            query = query.having(last_sold_expr < last_sold_before)

    query = query.options(
        selectinload(Product.sales_gl_code),
        selectinload(Product.gl_code_rel),
        selectinload(Product.locations),
        selectinload(Product.recipe_items).selectinload(ProductRecipeItem.item),
        selectinload(Product.recipe_items).selectinload(ProductRecipeItem.unit),
    )

    products = query.paginate(page=page, per_page=per_page)
    sales_gl_codes = (
        GLCode.query.filter(GLCode.code.like("4%")).order_by(GLCode.code).all()
    )
    selected_sales_gl_codes = (
        GLCode.query.filter(GLCode.id.in_(sales_gl_code_ids)).all()
        if sales_gl_code_ids
        else []
    )
    customers = Customer.query.order_by(Customer.last_name, Customer.first_name).all()
    selected_customer = Customer.query.get(customer_id) if customer_id else None
    return render_template(
        "products/view_products.html",
        products=products,
        delete_form=delete_form,
        form=create_form,
        name_query=name_query,
        match_mode=match_mode,
        sales_gl_code_ids=sales_gl_code_ids,
        sales_gl_codes=sales_gl_codes,
        selected_sales_gl_codes=selected_sales_gl_codes,
        customer_id=customer_id,
        customers=customers,
        selected_customer=selected_customer,
        cost_min=cost_min,
        cost_max=cost_max,
        price_min=price_min,
        price_max=price_max,
        last_sold_before=last_sold_before_str,
        include_unsold=include_unsold,
        bulk_cost_form=bulk_cost_form,
        per_page=per_page,
        pagination_args=build_pagination_args(per_page),
    )


@product.route("/products/create", methods=["GET", "POST"])
@login_required
def create_product():
    """Add a new product definition."""
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        yield_quantity = form.recipe_yield_quantity.data
        if yield_quantity is None or yield_quantity <= 0:
            yield_quantity = 1
        product = Product(
            name=form.name.data,
            price=form.price.data,
            cost=form.cost.data,  # Save cost
            gl_code=form.gl_code.data,
            gl_code_id=form.gl_code_id.data,
            sales_gl_code_id=form.sales_gl_code.data or None,
            recipe_yield_quantity=float(yield_quantity),
            recipe_yield_unit=form.recipe_yield_unit.data or None,
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
        log_activity(f"Created product {product.name}")
        flash("Product created successfully!", "success")
        return redirect(url_for("product.view_products"))
    if form.recipe_yield_quantity.data is None:
        form.recipe_yield_quantity.data = 1
    return render_template(
        "products/create_product.html", form=form, product_id=None
    )


@product.route("/products/ajax/create", methods=["POST"])
@login_required
def ajax_create_product():
    """Create a product via AJAX."""
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        yield_quantity = form.recipe_yield_quantity.data
        if yield_quantity is None or yield_quantity <= 0:
            yield_quantity = 1
        product = Product(
            name=form.name.data,
            price=form.price.data,
            cost=form.cost.data,
            gl_code=form.gl_code.data,
            gl_code_id=form.gl_code_id.data,
            sales_gl_code_id=form.sales_gl_code.data or None,
            recipe_yield_quantity=float(yield_quantity),
            recipe_yield_unit=form.recipe_yield_unit.data or None,
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
        log_activity(f"Created product {product.name}")
        row_html = render_template(
            "products/_product_row.html", product=product, delete_form=DeleteForm()
        )
        return jsonify(success=True, html=row_html)
    return jsonify(success=False, errors=form.errors), 400


@product.route("/products/quick-create", methods=["POST"])
@login_required
def quick_create_product():
    """Create a lightweight product record for use in menus."""

    form = QuickProductForm()
    if form.validate_on_submit():
        cost = form.cost.data if form.cost.data is not None else 0.0
        sales_gl_code_id = form.sales_gl_code.data or None
        if sales_gl_code_id == 0:
            sales_gl_code_id = None

        yield_quantity = form.recipe_yield_quantity.data
        if yield_quantity is None or yield_quantity <= 0:
            yield_quantity = 1

        product_obj = Product(
            name=form.name.data,
            price=form.price.data,
            cost=cost,
            sales_gl_code_id=sales_gl_code_id,
            recipe_yield_quantity=float(yield_quantity),
            recipe_yield_unit=form.recipe_yield_unit.data or None,
        )
        db.session.add(product_obj)
        db.session.flush()

        for item_form in form.items:
            item_id = item_form.item.data
            quantity = item_form.quantity.data
            if not item_id or quantity in (None, ""):
                continue
            unit_id = item_form.unit.data or None
            db.session.add(
                ProductRecipeItem(
                    product_id=product_obj.id,
                    item_id=item_id,
                    unit_id=unit_id,
                    quantity=quantity,
                    countable=item_form.countable.data,
                )
            )

        db.session.commit()
        log_activity(f"Quick created product {product_obj.name}")
        return (
            jsonify(
                success=True,
                product={"id": product_obj.id, "name": product_obj.name},
            ),
            201,
        )
    return jsonify(success=False, errors=form.errors), 400


@product.route("/products/ajax/validate", methods=["POST"])
@login_required
def validate_product_form():
    """Validate product form via AJAX without saving."""
    form = ProductWithRecipeForm()
    if form.validate_on_submit():
        return jsonify(success=True)
    return jsonify(success=False, errors=form.errors), 400


@product.route("/products/copy/<int:product_id>")
@login_required
def copy_product(product_id):
    """Provide a pre-filled form for duplicating a product."""
    product_obj = db.session.get(Product, product_id)
    if product_obj is None:
        abort(404)
    form = ProductWithRecipeForm()
    form.name.data = product_obj.name
    form.price.data = product_obj.price
    form.cost.data = product_obj.cost or 0.0
    form.gl_code.data = product_obj.gl_code
    form.gl_code_id.data = product_obj.gl_code_id
    form.sales_gl_code.data = product_obj.sales_gl_code_id
    form.recipe_yield_quantity.data = product_obj.recipe_yield_quantity or 1.0
    form.recipe_yield_unit.data = product_obj.recipe_yield_unit
    form.items.min_entries = len(product_obj.recipe_items)
    item_choices = [
        (itm.id, itm.name) for itm in Item.query.filter_by(archived=False).all()
    ]
    unit_choices = [(u.id, u.name) for u in ItemUnit.query.all()]
    for i, recipe_item in enumerate(product_obj.recipe_items):
        if len(form.items) <= i:
            form.items.append_entry()
        form.items[i].item.choices = item_choices
        form.items[i].unit.choices = unit_choices
        form.items[i].item.data = recipe_item.item_id
        form.items[i].unit.data = recipe_item.unit_id
        form.items[i].quantity.data = recipe_item.quantity
        form.items[i].countable.data = recipe_item.countable
    for i in range(len(product_obj.recipe_items), len(form.items)):
        form.items[i].item.choices = item_choices
        form.items[i].unit.choices = unit_choices
    return render_template(
        "products/create_product.html", form=form, product_id=None, title="Copy Product"
    )


@product.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
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
        yield_quantity = form.recipe_yield_quantity.data
        if yield_quantity is None or yield_quantity <= 0:
            yield_quantity = 1
        product.recipe_yield_quantity = float(yield_quantity)
        product.recipe_yield_unit = form.recipe_yield_unit.data or None
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
        log_activity(f"Edited product {product.id}")
        flash("Product updated successfully!", "success")
        return redirect(url_for("product.view_products"))
    elif request.method == "GET":
        form.name.data = product.name
        form.price.data = product.price
        form.cost.data = product.cost or 0.0  # 👈 Pre-fill cost
        form.gl_code.data = product.gl_code
        form.gl_code_id.data = product.gl_code_id
        form.sales_gl_code.data = product.sales_gl_code_id
        form.recipe_yield_quantity.data = product.recipe_yield_quantity or 1.0
        form.recipe_yield_unit.data = product.recipe_yield_unit
        form.items.min_entries = len(product.recipe_items)
        item_choices = [
            (itm.id, itm.name)
            for itm in Item.query.filter_by(archived=False).all()
        ]
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
    return render_template(
        "products/edit_product.html", form=form, product_id=product.id
    )


@product.route("/products/<int:product_id>/recipe", methods=["GET", "POST"])
@login_required
def edit_product_recipe(product_id):
    """Edit the recipe for a product."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    form = ProductRecipeForm()
    if form.validate_on_submit():
        yield_quantity = form.recipe_yield_quantity.data
        if yield_quantity is None or yield_quantity <= 0:
            yield_quantity = 1
        product.recipe_yield_quantity = float(yield_quantity)
        product.recipe_yield_unit = form.recipe_yield_unit.data or None
        ProductRecipeItem.query.filter_by(product_id=product.id).delete()
        items = [
            key
            for key in request.form.keys()
            if key.startswith("items-") and key.endswith("-item")
        ]
        for field in items:
            index = field.split("-")[1]
            item_id = request.form.get(f"items-{index}-item", type=int)
            unit_id = request.form.get(f"items-{index}-unit", type=int)
            quantity = coerce_float(request.form.get(f"items-{index}-quantity"))
            countable = request.form.get(f"items-{index}-countable") == "y"
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
        flash("Recipe updated successfully!", "success")
        return redirect(url_for("product.view_products"))
    elif request.method == "GET":
        form.recipe_yield_quantity.data = product.recipe_yield_quantity or 1.0
        form.recipe_yield_unit.data = product.recipe_yield_unit
        form.items.min_entries = max(1, len(product.recipe_items))
        item_choices = [
            (itm.id, itm.name)
            for itm in Item.query.filter_by(archived=False).all()
        ]
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
    return render_template(
        "products/edit_product_recipe.html", form=form, product=product
    )


@product.route("/products/<int:product_id>/calculate_cost")
@login_required
def calculate_product_cost(product_id):
    """Calculate the total recipe cost for a product."""
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    total = 0.0
    for ri in product.recipe_items:
        item_cost = getattr(ri.item, "cost", 0.0)
        try:
            qty = float(ri.quantity or 0)
        except (TypeError, ValueError):
            qty = 0
        factor = ri.unit.factor if ri.unit else 1
        total += (item_cost or 0) * qty * factor
    yield_override = coerce_float(request.args.get("yield_quantity"))
    yield_quantity = product.recipe_yield_quantity or 0
    if yield_override is not None and yield_override > 0:
        yield_quantity = yield_override
    if not yield_quantity or yield_quantity <= 0:
        yield_quantity = 1.0
    per_unit_cost = total / yield_quantity if yield_quantity else total
    return jsonify(
        {
            "cost": per_unit_cost,
            "batch_cost": total,
            "yield_quantity": yield_quantity,
            "yield_unit": product.recipe_yield_unit,
        }
    )


@product.route("/products/bulk_set_cost_from_recipe", methods=["POST"])
@login_required
def bulk_set_cost_from_recipe():
    """Recalculate cost from recipe for selected products."""
    form = BulkProductCostForm()
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url_for("product.view_products"))

    raw_ids = request.form.getlist("product_ids")
    product_ids = []
    for raw_id in raw_ids:
        try:
            product_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    query = Product.query.options(
        selectinload(Product.recipe_items).selectinload(ProductRecipeItem.item),
        selectinload(Product.recipe_items).selectinload(ProductRecipeItem.unit),
    )
    if product_ids:
        query = query.filter(Product.id.in_(product_ids))

    products = query.all()
    if not products:
        flash("No products selected for recipe cost update.", "warning")
        return redirect(url_for("product.view_products"))

    updated = 0
    for product_obj in products:
        total = 0.0
        for recipe_item in product_obj.recipe_items:
            item_cost = getattr(recipe_item.item, "cost", 0.0)
            try:
                quantity = float(recipe_item.quantity or 0)
            except (TypeError, ValueError):
                quantity = 0.0
            factor = recipe_item.unit.factor if recipe_item.unit else 1
            total += (item_cost or 0.0) * quantity * factor
        yield_quantity = product_obj.recipe_yield_quantity or 0
        if not yield_quantity or yield_quantity <= 0:
            yield_quantity = 1.0
        product_obj.cost = total / yield_quantity if yield_quantity else total
        updated += 1

    db.session.commit()
    log_activity(
        f"Bulk updated product cost from recipe for {updated} product"
        f"{'s' if updated != 1 else ''}"
    )
    flash(
        f"Updated recipe cost for {updated} product{'s' if updated != 1 else ''}.",
        "success",
    )
    return redirect(url_for("product.view_products"))


@product.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    """Delete a product and its recipe."""
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    db.session.delete(product)
    db.session.commit()
    log_activity(f"Deleted product {product.id}")
    flash("Product deleted successfully!", "success")
    return redirect(url_for("product.view_products"))


@product.route("/search_products")
def search_products():
    """Return products matching a search query."""
    # Retrieve query parameter from the URL
    query = request.args.get("query", "").lower()
    # Query the database for products that match the search query
    matched_products = Product.query.filter(
        Product.name.ilike(f"%{query}%")
    ).all()
    # Include id so that search results can be referenced elsewhere
    product_data = [
        {"id": product.id, "name": product.name, "price": product.price}
        for product in matched_products
    ]
    # Return matched product names and prices as JSON
    return jsonify(product_data)
