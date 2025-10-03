from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy.orm import selectinload

from app import db
from app.forms import CSRFOnlyForm, MenuAssignmentForm, MenuForm
from app.models import Location, Menu, MenuAssignment, Product
from app.utils.activity import log_activity
from app.utils.menu_assignments import set_location_menu, sync_menu_locations

menu = Blueprint("menu", __name__)


def _load_products(product_ids: list[int]) -> list[Product]:
    if not product_ids:
        return []
    unique_ids = list(dict.fromkeys(product_ids))
    products = Product.query.filter(Product.id.in_(unique_ids)).all()
    by_id = {product.id: product for product in products}
    return [by_id[pid] for pid in unique_ids if pid in by_id]


@menu.route("/menus")
@login_required
def view_menus():
    menus = (
        Menu.query.options(
            selectinload(Menu.products),
            selectinload(Menu.assignments).selectinload(MenuAssignment.location),
        )
        .order_by(Menu.name)
        .all()
    )
    delete_form = CSRFOnlyForm()
    return render_template(
        "menus/view_menus.html", menus=menus, delete_form=delete_form
    )


@menu.route("/menus/add", methods=["GET", "POST"])
@login_required
def add_menu():
    form = MenuForm()
    if form.validate_on_submit():
        menu = Menu(
            name=form.name.data,
            description=form.description.data,
        )
        menu.products = _load_products(form.product_ids.data)
        db.session.add(menu)
        db.session.commit()
        log_activity(f"Created menu {menu.name}")
        flash("Menu created successfully.", "success")
        return redirect(url_for("menu.view_menus"))
    return render_template("menus/edit_menu.html", form=form, menu=None)


@menu.route("/menus/<int:menu_id>/edit", methods=["GET", "POST"])
@login_required
def edit_menu(menu_id: int):
    menu = db.session.get(Menu, menu_id)
    if menu is None:
        abort(404)
    form = MenuForm(obj=menu, obj_id=menu.id)
    if request.method == "GET":
        form.product_ids.data = [product.id for product in menu.products]
    if form.validate_on_submit():
        menu.name = form.name.data
        menu.description = form.description.data
        menu.products = _load_products(form.product_ids.data)
        db.session.flush()
        sync_menu_locations(menu)
        db.session.commit()
        log_activity(f"Updated menu {menu.name}")
        flash("Menu updated successfully.", "success")
        return redirect(url_for("menu.view_menus"))
    return render_template("menus/edit_menu.html", form=form, menu=menu)


@menu.route("/menus/<int:menu_id>/delete", methods=["POST"])
@login_required
def delete_menu(menu_id: int):
    form = CSRFOnlyForm()
    if not form.validate_on_submit():
        flash("Unable to validate deletion request.", "danger")
        return redirect(url_for("menu.view_menus"))
    menu = db.session.get(Menu, menu_id)
    if menu is None:
        abort(404)
    active_locations = [assignment.location for assignment in menu.assignments if assignment.unassigned_at is None and assignment.location]
    for location in active_locations:
        set_location_menu(location, None)
    db.session.delete(menu)
    db.session.commit()
    log_activity(f"Deleted menu {menu.name}")
    flash("Menu deleted successfully.", "success")
    return redirect(url_for("menu.view_menus"))


@menu.route("/menus/<int:menu_id>/assign", methods=["GET", "POST"])
@login_required
def assign_menu(menu_id: int):
    menu = db.session.get(Menu, menu_id)
    if menu is None:
        abort(404)
    form = MenuAssignmentForm()
    if request.method == "GET":
        form.location_ids.data = [loc.id for loc in Location.query.filter_by(current_menu_id=menu.id).all()]
    if form.validate_on_submit():
        selected_ids = set(form.location_ids.data)
        current_locations = Location.query.filter_by(current_menu_id=menu.id).all()
        for location in current_locations:
            if location.id not in selected_ids:
                set_location_menu(location, None)
        if selected_ids:
            locations = Location.query.filter(Location.id.in_(selected_ids)).all()
            for location in locations:
                set_location_menu(location, menu)
        db.session.commit()
        log_activity(
            "Updated menu assignments for {name}".format(name=menu.name)
        )
        flash("Menu assignments updated.", "success")
        return redirect(url_for("menu.view_menus"))
    return render_template("menus/assign_menu.html", form=form, menu=menu)
