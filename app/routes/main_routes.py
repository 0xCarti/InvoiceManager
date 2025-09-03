from flask import Blueprint, render_template
from flask_login import current_user, login_required

main = Blueprint("main", __name__)


@main.route("/")
@login_required
def home():
    """Render the transfers dashboard."""
    return render_template("transfers/view_transfers.html", user=current_user)
