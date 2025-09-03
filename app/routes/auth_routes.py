# flake8: noqa
import os
import platform
import subprocess
from datetime import datetime
from urllib.parse import urlparse

import flask
from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import NotFound
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join, secure_filename

from app import limiter
from app.forms import (ChangePasswordForm, CreateBackupForm, ImportForm,
                       InviteUserForm, LoginForm, NotificationForm,
                       PasswordResetRequestForm, RestoreBackupForm,
                       SetPasswordForm, SettingsForm, TimezoneForm, UserForm)
from app.models import (ActivityLog, Customer, GLCode, Invoice, Setting,
                        Transfer, User, Vendor, db)
from app.utils import send_email
from app.utils.activity import log_activity
from app.utils.backup import create_backup, restore_backup
from app.utils.imports import (_import_csv, _import_items, _import_locations,
                               _import_products)

auth = Blueprint("auth", __name__)
admin = Blueprint("admin", __name__)

IMPORT_FILES = {
    "locations": "example_locations.csv",
    "products": "example_products.csv",
    "gl_codes": "example_gl_codes.csv",
    "items": "example_items.csv",
    "customers": "example_customers.csv",
    "vendors": "example_vendors.csv",
    "users": "example_users.csv",
}


def _serializer():
    from flask import current_app

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_reset_token(user_id: int) -> str:
    return _serializer().dumps({"user_id": user_id})


def verify_reset_token(token: str, max_age: int = 3600):
    try:
        data = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return db.session.get(User, data.get("user_id"))


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    """Authenticate a user and start their session."""
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash("Please check your login details and try again.")
            return redirect(url_for("auth.login"))
        elif not user.active:
            flash("Please contact system admin to activate account.")
            return redirect(url_for("auth.login"))

        login_user(user)
        log_activity("Logged in", user.id)
        return redirect(url_for("transfer.view_transfers"))

    from run import app

    return render_template("auth/login.html", form=form, demo=app.config["DEMO"])


@auth.route("/logout")
@login_required
def logout():
    """Log the current user out."""
    user_id = current_user.id
    logout_user()
    log_activity("Logged out", user_id)
    return redirect(url_for("auth.login"))


@auth.route("/reset", methods=["GET", "POST"])
@limiter.limit("3 per hour")
def reset_request():
    """Request a password reset email."""
    form = PasswordResetRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if not user:
            flash("No account found with that email.", "danger")
            return render_template("auth/reset_request.html", form=form)

        token = generate_reset_token(user.id)
        reset_url = url_for("auth.reset_token", token=token, _external=True)
        send_email(
            user.email,
            "Password Reset",
            f"Click the link to reset your password: {reset_url}",
        )
        flash("A reset link has been sent to your email.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_request.html", form=form)


@auth.route("/reset/<token>", methods=["GET", "POST"])
def reset_token(token):
    """Set a new password using a reset token."""
    user = verify_reset_token(token)
    if not user:
        flash("Invalid or expired token.", "danger")
        return redirect(url_for("auth.reset_request"))

    form = SetPasswordForm()
    if form.validate_on_submit():
        user.password = generate_password_hash(form.new_password.data)
        db.session.commit()
        flash("Password updated.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_token.html", form=form)


@auth.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Allow the current user to change their password."""
    form = ChangePasswordForm()
    tz_form = TimezoneForm(timezone=current_user.timezone or "")
    notif_form = NotificationForm(
        phone_number=current_user.phone_number or "",
        notify_transfers=current_user.notify_transfers,
    )
    if form.validate_on_submit():
        if not check_password_hash(current_user.password, form.current_password.data):
            flash("Current password incorrect.", "danger")
        else:
            current_user.password = generate_password_hash(form.new_password.data)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("auth.profile"))
    elif "timezone" in request.form and tz_form.validate_on_submit():
        current_user.timezone = tz_form.timezone.data or None
        db.session.commit()
        flash("Timezone updated.", "success")
        return redirect(url_for("auth.profile"))
    elif (
        "phone_number" in request.form or "notify_transfers" in request.form
    ) and notif_form.validate_on_submit():
        current_user.phone_number = notif_form.phone_number.data or None
        current_user.notify_transfers = notif_form.notify_transfers.data or False
        db.session.commit()
        flash("Notification settings updated.", "success")
        return redirect(url_for("auth.profile"))

    transfers = Transfer.query.filter_by(user_id=current_user.id).all()
    invoices = Invoice.query.filter_by(user_id=current_user.id).all()
    return render_template(
        "profile.html",
        user=current_user,
        form=form,
        tz_form=tz_form,
        notif_form=notif_form,
        transfers=transfers,
        invoices=invoices,
    )


@auth.route("/favorite/<path:link>")
@login_required
def toggle_favorite(link):
    """Toggle a navigation link as favourite for the current user."""
    current_user.toggle_favorite(link)
    db.session.commit()
    referrer = request.referrer
    if referrer:
        safe_referrer = referrer.replace("\\", "")
        parsed = urlparse(safe_referrer)
        if not parsed.scheme and not parsed.netloc:
            return redirect(safe_referrer)
    return redirect(url_for("main.home"))


@admin.route("/user_profile/<int:user_id>", methods=["GET", "POST"])
@login_required
def user_profile(user_id):
    """View or update another user's profile."""
    if not current_user.is_admin:
        abort(403)

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    form = SetPasswordForm()
    tz_form = TimezoneForm(timezone=user.timezone or "")
    notif_form = NotificationForm(
        phone_number=user.phone_number or "",
        notify_transfers=user.notify_transfers,
    )
    if form.validate_on_submit():
        user.password = generate_password_hash(form.new_password.data)
        db.session.commit()
        flash("Password updated.", "success")
        return redirect(url_for("admin.user_profile", user_id=user_id))
    elif "timezone" in request.form and tz_form.validate_on_submit():
        user.timezone = tz_form.timezone.data or None
        db.session.commit()
        flash("Timezone updated.", "success")
        return redirect(url_for("admin.user_profile", user_id=user_id))
    elif (
        "phone_number" in request.form or "notify_transfers" in request.form
    ) and notif_form.validate_on_submit():
        user.phone_number = notif_form.phone_number.data or None
        user.notify_transfers = notif_form.notify_transfers.data or False
        db.session.commit()
        flash("Notification settings updated.", "success")
        return redirect(url_for("admin.user_profile", user_id=user_id))

    transfers = Transfer.query.filter_by(user_id=user.id).all()
    invoices = Invoice.query.filter_by(user_id=user.id).all()
    return render_template(
        "profile.html",
        user=user,
        form=form,
        tz_form=tz_form,
        notif_form=notif_form,
        transfers=transfers,
        invoices=invoices,
    )


@admin.route("/activate_user/<int:user_id>", methods=["GET"])
@login_required
def activate_user(user_id):
    """Activate a user account."""
    if not current_user.is_admin:
        abort(403)  # Abort if the current user is not an admin

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    user.active = True
    db.session.commit()
    log_activity(f"Activated user {user_id}")
    flash("User account activated.", "success")
    return redirect(url_for("admin.users"))  # Redirect to the user control panel


@admin.route("/controlpanel/users", methods=["GET", "POST"])
@login_required
def users():
    """Admin interface for managing users."""
    if not current_user.is_admin:
        return abort(403)  # Only allow admins to access this page

    users = User.query.all()  # Fetch all users from the database

    form = UserForm()
    invite_form = InviteUserForm()

    if invite_form.submit.data and invite_form.validate_on_submit():
        email = invite_form.email.data
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("User already exists.", "danger")
        else:
            temp_password = generate_password_hash(os.urandom(16).hex())
            new_user = User(
                email=email, password=temp_password, active=False, is_admin=False
            )
            db.session.add(new_user)
            db.session.commit()
            token = generate_reset_token(new_user.id)
            invite_url = url_for("auth.reset_token", token=token, _external=True)
            send_email(
                email,
                "You are invited to InvoiceManager",
                f"Click the link to set your password: {invite_url}",
            )
            flash("Invitation sent.", "success")
        return redirect(url_for("admin.users"))

    if request.method == "POST" and form.validate_on_submit():
        user_id = request.args.get("user_id")
        action = request.form.get("action")

        user = User.query.filter_by(id=user_id).first()
        if user:
            if action == "toggle_active":
                user.active = not user.active
                log_activity(f"Toggled active for user {user_id}")
            elif action == "toggle_admin":
                user.is_admin = not user.is_admin
                log_activity(f"Toggled admin for user {user_id}")
            db.session.commit()
            flash("User updated successfully", "success")
        else:
            flash("User not found", "danger")

        return redirect(url_for("admin.users"))

    return render_template(
        "admin/view_users.html", users=users, form=form, invite_form=invite_form
    )


@admin.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    """Remove a user from the system."""
    if not current_user.is_admin:
        abort(403)  # Abort if the current user is not an admin

    user_to_delete = db.session.get(User, user_id)
    if user_to_delete is None:
        abort(404)
    user_to_delete.active = False
    db.session.commit()
    log_activity(f"Archived user {user_id}")
    flash("User archived successfully.", "success")
    return redirect(url_for("admin.users"))


@admin.route("/controlpanel/backups", methods=["GET"])
@login_required
def backups():
    """List available database backups."""
    if not current_user.is_admin:
        abort(403)
    from flask import current_app

    backups_dir = current_app.config["BACKUP_FOLDER"]
    os.makedirs(backups_dir, exist_ok=True)
    files = sorted(os.listdir(backups_dir))
    create_form = CreateBackupForm()
    restore_form = RestoreBackupForm()
    return render_template(
        "admin/backups.html",
        backups=files,
        create_form=create_form,
        restore_form=restore_form,
    )


@admin.route("/controlpanel/backups/create", methods=["POST"])
@login_required
def create_backup_route():
    """Create a new database backup."""
    if not current_user.is_admin:
        abort(403)
    form = CreateBackupForm()
    if form.validate_on_submit():
        filename = create_backup()
        log_activity(f"Created backup {filename}")
        flash("Backup created: " + filename, "success")
    return redirect(url_for("admin.backups"))


@admin.route("/controlpanel/backups/restore", methods=["POST"])
@login_required
def restore_backup_route():
    """Restore the database from an uploaded backup."""
    if not current_user.is_admin:
        abort(403)
    form = RestoreBackupForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        from flask import current_app

        backups_dir = current_app.config["BACKUP_FOLDER"]
        os.makedirs(backups_dir, exist_ok=True)
        filepath = os.path.join(backups_dir, filename)
        file.save(filepath)
        restore_backup(filepath)
        log_activity(f"Restored backup {filename}")
        flash("Backup restored from " + filename, "success")
    return redirect(url_for("admin.backups"))


@admin.route("/controlpanel/backups/restore/<path:filename>", methods=["POST"])
@login_required
def restore_backup_file(filename):
    """Restore the database from an existing backup file."""
    if not current_user.is_admin:
        abort(403)
    from flask import current_app

    backups_dir = current_app.config["BACKUP_FOLDER"]
    try:
        filepath = safe_join(backups_dir, filename)
    except NotFound:
        abort(404)
    if filepath is None or not os.path.isfile(filepath):
        abort(404)
    restore_backup(filepath)
    fname = os.path.basename(filepath)
    log_activity(f"Restored backup {fname}")
    flash("Backup restored from " + fname, "success")
    return redirect(url_for("admin.backups"))


@admin.route("/controlpanel/backups/download/<path:filename>", methods=["GET"])
@login_required
def download_backup(filename):
    """Download a backup file."""
    if not current_user.is_admin:
        abort(403)
    from flask import current_app, send_from_directory

    backups_dir = current_app.config["BACKUP_FOLDER"]
    log_activity(f"Downloaded backup {filename}")
    return send_from_directory(backups_dir, filename, as_attachment=True)


@admin.route("/controlpanel/activity", methods=["GET"])
@login_required
def activity_logs():
    """Display a log of user actions."""
    if not current_user.is_admin:
        abort(403)
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template("admin/activity_logs.html", logs=logs)


@admin.route("/controlpanel/system", methods=["GET"])
@login_required
def system_info():
    """Display runtime system information."""
    if not current_user.is_admin:
        abort(403)
    start = current_app.config.get("START_TIME")
    uptime = None
    if start:
        uptime = datetime.utcnow() - start
    try:
        version = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode()
            .strip()
        )
    except Exception:
        version = "unknown"
    info = {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "flask_version": flask.__version__,
        "version": version,
        "started_at": start,
        "uptime": str(uptime).split(".")[0] if uptime else "unknown",
    }
    return render_template("admin/system_info.html", info=info)


@admin.route("/controlpanel/imports", methods=["GET"])
@login_required
def import_page():
    """Display import options."""
    if not current_user.is_admin:
        abort(403)
    forms = {key: ImportForm(prefix=key) for key in IMPORT_FILES}
    labels = {
        "locations": "Import Locations",
        "products": "Import Products",
        "gl_codes": "Import GL Codes",
        "items": "Import Items",
        "customers": "Import Customers",
        "vendors": "Import Vendors",
        "users": "Import Users",
    }
    return render_template("admin/imports.html", forms=forms, labels=labels)


@admin.route("/controlpanel/import/<string:data_type>", methods=["POST"])
@login_required
def import_data(data_type):
    """Import a specific data type from an uploaded CSV file."""
    from flask import current_app

    if not current_user.is_admin:
        abort(403)
    form = ImportForm(prefix=data_type)
    if not form.validate_on_submit() or data_type not in IMPORT_FILES:
        abort(400)

    file = form.file.data
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".csv"):
        flash("Please upload a CSV file.", "error")
        return redirect(url_for("admin.import_page"))

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, filename)
    file.save(path)

    try:
        if data_type == "locations":
            count = _import_locations(path)
        elif data_type == "products":
            count = _import_products(path)
        elif data_type == "gl_codes":
            count = _import_csv(
                path, GLCode, {"code": "code", "description": "description"}
            )
        elif data_type == "items":
            count = _import_items(path)
        elif data_type == "customers":
            count = _import_csv(
                path,
                Customer,
                {
                    "first_name": "first_name",
                    "last_name": "last_name",
                },
            )
        elif data_type == "vendors":
            count = _import_csv(
                path,
                Vendor,
                {
                    "first_name": "first_name",
                    "last_name": "last_name",
                },
            )
        elif data_type == "users":
            count = _import_csv(path, User, {"email": "email", "password": "password"})
        else:
            abort(400)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.import_page"))
    finally:
        if os.path.exists(path):
            os.remove(path)
    flash(f'Imported {count} {data_type.replace("_", " ")}.', "success")
    return redirect(url_for("admin.import_page"))


@admin.route("/controlpanel/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Allow admins to update application settings like GST number."""
    if not current_user.is_admin:
        abort(403)

    gst_setting = Setting.query.filter_by(name="GST").first()
    if gst_setting is None:
        gst_setting = Setting(name="GST", value="")
        db.session.add(gst_setting)

    tz_setting = Setting.query.filter_by(name="DEFAULT_TIMEZONE").first()
    if tz_setting is None:
        tz_setting = Setting(name="DEFAULT_TIMEZONE", value="UTC")
        db.session.add(tz_setting)
    db.session.commit()

    form = SettingsForm(gst_number=gst_setting.value, default_timezone=tz_setting.value)
    if form.validate_on_submit():
        gst_setting.value = form.gst_number.data or ""
        tz_setting.value = form.default_timezone.data or "UTC"
        db.session.commit()
        import app

        app.GST = gst_setting.value
        app.DEFAULT_TIMEZONE = tz_setting.value
        flash("Settings updated.", "success")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", form=form)
