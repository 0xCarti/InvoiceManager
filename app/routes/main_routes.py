from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.services.dashboard_metrics import dashboard_context

main = Blueprint("main", __name__)


@main.route("/")
@login_required
def home():
    """Render the dashboard with aggregated context."""

    from app.forms import TransferForm

    context = dashboard_context()
    form = TransferForm()
    add_form = TransferForm(prefix="add")
    edit_form = TransferForm(prefix="edit")

    return render_template(
        "dashboard.html",
        user=current_user,
        context=context,
        form=form,
        add_form=add_form,
        edit_form=edit_form,
    )
