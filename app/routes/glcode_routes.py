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

from app import db
from app.forms import DeleteForm, GLCodeForm
from app.models import GLCode

glcode_bp = Blueprint("glcode", __name__)


@glcode_bp.route("/gl_codes")
@login_required
def view_gl_codes():
    """List GL codes."""
    page = request.args.get("page", 1, type=int)
    codes = GLCode.query.order_by(GLCode.code).paginate(page=page, per_page=20)
    delete_form = DeleteForm()
    form = GLCodeForm()
    return render_template(
        "gl_codes/view_gl_codes.html",
        codes=codes,
        delete_form=delete_form,
        form=form,
    )


@glcode_bp.route("/gl_codes/create", methods=["GET", "POST"])
@login_required
def create_gl_code():
    """Create a new GL code."""
    form = GLCodeForm()
    if form.validate_on_submit():
        code = GLCode(code=form.code.data, description=form.description.data)
        db.session.add(code)
        db.session.commit()
        flash("GL Code created successfully!", "success")
        return redirect(url_for("glcode.view_gl_codes"))
    return render_template("gl_codes/add_gl_code.html", form=form)


@glcode_bp.route("/gl_codes/<int:code_id>/edit", methods=["GET", "POST"])
@login_required
def edit_gl_code(code_id):
    """Edit an existing GL code."""
    code = db.session.get(GLCode, code_id)
    if code is None:
        abort(404)
    form = GLCodeForm(obj=code)
    if form.validate_on_submit():
        code.code = form.code.data
        code.description = form.description.data
        db.session.commit()
        flash("GL Code updated successfully!", "success")
        return redirect(url_for("glcode.view_gl_codes"))
    return render_template("gl_codes/edit_gl_code.html", form=form)


@glcode_bp.route("/gl_codes/<int:code_id>/delete", methods=["POST"])
@login_required
def delete_gl_code(code_id):
    """Delete a GL code."""
    form = DeleteForm()
    if not form.validate_on_submit():
        abort(400)
    code = db.session.get(GLCode, code_id)
    if code is None:
        abort(404)
    db.session.delete(code)
    db.session.commit()
    flash("GL Code deleted successfully!", "success")
    return redirect(url_for("glcode.view_gl_codes"))


@glcode_bp.route("/gl_codes/ajax/create", methods=["POST"])
@login_required
def ajax_create_gl_code():
    """Create a GL code via AJAX."""
    form = GLCodeForm()
    if form.validate_on_submit():
        code = GLCode(code=form.code.data, description=form.description.data)
        db.session.add(code)
        db.session.commit()
        return {
            "success": True,
            "id": code.id,
            "code": code.code,
            "description": code.description or "",
        }
    return {"success": False, "errors": form.errors}, 400


@glcode_bp.route("/gl_codes/<int:code_id>/ajax/update", methods=["POST"])
@login_required
def ajax_update_gl_code(code_id):
    """Update a GL code via AJAX."""
    code = db.session.get(GLCode, code_id)
    if code is None:
        abort(404)
    form = GLCodeForm()
    if form.validate_on_submit():
        code.code = form.code.data
        code.description = form.description.data
        db.session.commit()
        return {
            "success": True,
            "id": code.id,
            "code": code.code,
            "description": code.description or "",
        }
    return {"success": False, "errors": form.errors}, 400
