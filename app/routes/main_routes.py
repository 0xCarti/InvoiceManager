from flask import Blueprint, render_template
from flask_login import current_user, login_required

main = Blueprint("main", __name__)


@main.route("/")
@login_required
def home():
    """Render the transfers dashboard."""
    from app.forms import TransferForm

    form = TransferForm()
    add_form = TransferForm(prefix="add")
    edit_form = TransferForm(prefix="edit")
    return render_template(
        "transfers/view_transfers.html",
        user=current_user,
        form=form,
        add_form=add_form,
        edit_form=edit_form,
    )
