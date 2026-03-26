import json
import os
import platform
import sqlite3
import subprocess
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import flask
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.orm import selectinload
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import NotFound
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join, secure_filename

from app import limiter
from app.forms import (
    ActivityLogFilterForm,
    ChangePasswordForm,
    CreateBackupForm,
    DeleteForm,
    ImportForm,
    InviteUserForm,
    LoginForm,
    NotificationForm,
    PasswordResetRequestForm,
    RestoreBackupForm,
    SetPasswordForm,
    SettingsForm,
    TerminalSalesMappingDeleteForm,
    TimezoneForm,
    VendorItemAliasForm,
    UserForm,
    MAX_BACKUP_SIZE,
    PURCHASE_RECEIVE_DEPARTMENT_CONFIG,
)
from app.models import (
    ActivityLog,
    Customer,
    GLCode,
    Location,
    Invoice,
    PosSalesImport,
    PosSalesImportLocation,
    PosSalesImportRow,
    Product,
    Setting,
    TerminalSaleLocationAlias,
    TerminalSaleProductAlias,
    VendorItemAlias,
    Transfer,
    User,
    Vendor,
    db,
)
from app.utils import send_email
from app.utils.activity import log_activity
from app.utils.backup import (
    UNIT_SECONDS,
    create_backup,
    restore_backup,
    start_auto_backup_thread,
    validate_backup_file_compatibility,
)
from app.utils.imports import (
    _import_csv,
    _import_items,
    _import_locations,
    _import_products,
)
from app.services.purchase_imports import (
    normalize_vendor_alias_text,
    update_or_create_vendor_alias,
)
from app.utils.units import (
    DEFAULT_BASE_UNIT_CONVERSIONS,
    get_allowed_target_units,
    parse_conversion_setting,
    serialize_conversion_setting,
)
from app.utils.pos_import import normalize_pos_alias

auth = Blueprint("auth", __name__)
admin = Blueprint("admin", __name__)

# Only .db files are accepted for database restoration uploads
ALLOWED_BACKUP_EXTENSIONS = {".db"}

IMPORT_FILES = {
    "locations": "example_locations.csv",
    "products": "example_products.csv",
    "gl_codes": "example_gl_codes.csv",
    "items": "example_items.csv",
    "customers": "example_customers.csv",
    "vendors": "example_vendors.csv",
    "users": "example_users.csv",
}


def _cleanup_restored_user_favorites() -> int:
    """Remove stale favourite endpoints after a backup restore."""

    valid_endpoints = {rule.endpoint for rule in current_app.url_map.iter_rules()}
    users = User.query.all()
    changed = 0

    for user in users:
        favorites = [f for f in (user.favorites or "").split(",") if f]
        filtered = [favorite for favorite in favorites if favorite in valid_endpoints]
        if filtered != favorites:
            user.favorites = ",".join(filtered)
            changed += 1

    if changed:
        db.session.commit()

    return changed


def _apply_restore_favorites_mode(ignore_favorites: bool) -> tuple[str, int]:
    """Apply post-restore favorites behavior and return mode + changed count."""

    if ignore_favorites:
        changed = (
            User.query.filter(User.favorites.isnot(None), User.favorites != "")
            .update({User.favorites: ""}, synchronize_session=False)
        )
        db.session.commit()
        return "ignored", changed

    cleaned_count = _cleanup_restored_user_favorites()
    return "cleaned", cleaned_count


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

        now = datetime.utcnow()
        user.last_login_at = now
        user.last_active_at = now
        user.last_forced_login_at = now
        db.session.commit()
        login_user(user, remember=form.remember.data)
        log_activity("Logged in", user.id)
        return redirect(url_for("transfer.view_transfers"))

    from run import app

    return render_template(
        "auth/login.html", form=form, demo=app.config["DEMO"]
    )


@auth.route("/logout")
@login_required
def logout():
    """Log the current user out."""
    user_id = current_user.id
    logout_user()
    log_activity("Logged out", user_id)
    return redirect(url_for("auth.login"))


@admin.route("/zero-threat.html", methods=["GET", "POST"])
def zerothreat():
    return render_template("auth/zero-threat.html")
    

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
    status_messages = {}
    if request.args.get("password_status") == "updated":
        status_messages["password"] = ("success", "Password updated.")
    if request.args.get("timezone_status") == "updated":
        status_messages["timezone"] = ("success", "Timezone updated.")
    if request.args.get("notifications_status") == "updated":
        status_messages["notifications"] = (
            "success",
            "Notification settings updated.",
        )

    password_submitted = "new_password" in request.form
    timezone_submitted = "timezone" in request.form
    notifications_submitted = (
        "phone_number" in request.form or "notify_transfers" in request.form
    )

    if password_submitted and form.validate_on_submit():
        if not check_password_hash(
            current_user.password, form.current_password.data
        ):
            form.current_password.errors.append("Current password incorrect.")
        else:
            current_user.password = generate_password_hash(
                form.new_password.data
            )
            db.session.commit()
            return redirect(url_for("auth.profile", password_status="updated"))
    elif timezone_submitted and tz_form.validate_on_submit():
        current_user.timezone = tz_form.timezone.data or None
        db.session.commit()
        return redirect(url_for("auth.profile", timezone_status="updated"))
    elif notifications_submitted and notif_form.validate_on_submit():
        current_user.phone_number = notif_form.phone_number.data or None
        current_user.notify_transfers = (
            notif_form.notify_transfers.data or False
        )
        db.session.commit()
        return redirect(
            url_for("auth.profile", notifications_status="updated")
        )

    transfers = (
        Transfer.query.filter_by(user_id=current_user.id)
        .order_by(Transfer.date_created.desc(), Transfer.id.desc())
        .all()
    )
    invoices = (
        Invoice.query.filter_by(user_id=current_user.id)
        .order_by(Invoice.date_created.desc(), Invoice.id.desc())
        .all()
    )
    return render_template(
        "profile.html",
        user=current_user,
        form=form,
        tz_form=tz_form,
        notif_form=notif_form,
        status_messages=status_messages,
        password_submitted=password_submitted,
        timezone_submitted=timezone_submitted,
        notifications_submitted=notifications_submitted,
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
    status_messages = {}
    if request.args.get("password_status") == "updated":
        status_messages["password"] = ("success", "Password updated.")
    if request.args.get("timezone_status") == "updated":
        status_messages["timezone"] = ("success", "Timezone updated.")
    if request.args.get("notifications_status") == "updated":
        status_messages["notifications"] = (
            "success",
            "Notification settings updated.",
        )

    password_submitted = "new_password" in request.form
    timezone_submitted = "timezone" in request.form
    notifications_submitted = (
        "phone_number" in request.form or "notify_transfers" in request.form
    )

    if password_submitted and form.validate_on_submit():
        user.password = generate_password_hash(form.new_password.data)
        db.session.commit()
        return redirect(
            url_for(
                "admin.user_profile", user_id=user_id, password_status="updated"
            )
        )
    elif timezone_submitted and tz_form.validate_on_submit():
        user.timezone = tz_form.timezone.data or None
        db.session.commit()
        return redirect(
            url_for(
                "admin.user_profile", user_id=user_id, timezone_status="updated"
            )
        )
    elif notifications_submitted and notif_form.validate_on_submit():
        user.phone_number = notif_form.phone_number.data or None
        user.notify_transfers = notif_form.notify_transfers.data or False
        db.session.commit()
        return redirect(
            url_for(
                "admin.user_profile",
                user_id=user_id,
                notifications_status="updated",
            )
        )

    transfers = (
        Transfer.query.filter_by(user_id=user.id)
        .order_by(Transfer.date_created.desc(), Transfer.id.desc())
        .all()
    )
    invoices = (
        Invoice.query.filter_by(user_id=user.id)
        .order_by(Invoice.date_created.desc(), Invoice.id.desc())
        .all()
    )
    return render_template(
        "profile.html",
        user=user,
        form=form,
        tz_form=tz_form,
        notif_form=notif_form,
        status_messages=status_messages,
        password_submitted=password_submitted,
        timezone_submitted=timezone_submitted,
        notifications_submitted=notifications_submitted,
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
    return redirect(
        url_for("admin.users")
    )  # Redirect to the user control panel


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
                email=email,
                password=temp_password,
                active=False,
                is_admin=False,
            )
            db.session.add(new_user)
            db.session.commit()
            token = generate_reset_token(new_user.id)
            invite_url = url_for(
                "auth.reset_token", token=token, _external=True
            )
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
        "admin/view_users.html",
        users=users,
        form=form,
        invite_form=invite_form,
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
        ext = os.path.splitext(filename)[1].lower()
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if ext not in ALLOWED_BACKUP_EXTENSIONS:
            flash("Only .db files are allowed.", "error")
            return redirect(url_for("admin.backups"))
        if size > MAX_BACKUP_SIZE:
            flash("File is too large.", "error")
            return redirect(url_for("admin.backups"))
        from flask import current_app

        backups_dir = current_app.config["BACKUP_FOLDER"]
        os.makedirs(backups_dir, exist_ok=True)
        filepath = os.path.join(backups_dir, filename)
        file.save(filepath)
        try:
            compatibility = validate_backup_file_compatibility(filepath)
        except sqlite3.Error:
            os.remove(filepath)
            flash("Invalid SQLite database.", "error")
            return redirect(url_for("admin.backups"))
        if not compatibility.compatible:
            details = "; ".join(compatibility.issues)
            current_app.logger.warning(
                "Restore preflight incompatibility detected for %s: %s",
                filename,
                details,
            )
            log_activity(
                f"Restore blocked due to compatibility errors for {filename}: {details}"
            )
            flash(
                "⚠️ Incompatible backup: this backup is missing critical database "
                "structures and cannot be restored safely.",
                "danger",
            )
            return redirect(url_for("admin.backups"))

        if compatibility.warnings:
            warning_details = "; ".join(compatibility.warnings)
            current_app.logger.warning(
                "Restore preflight compatibility warnings for %s: %s",
                filename,
                warning_details,
            )
            log_activity(
                f"Restore compatibility warnings detected for {filename}: {warning_details}"
            )

        restore_backup(filepath)
        mode, changed_count = _apply_restore_favorites_mode(
            bool(form.ignore_favorites.data)
        )
        if compatibility.warnings:
            flash("Restored with compatibility warnings.", "warning")

        if mode == "ignored":
            log_activity(
                f"Cleared favorites for {changed_count} user(s) after restore {filename} (ignore_favorites=true)"
            )
            flash(
                f"Backup restored from {filename}. Favorites mode: ignored backup favorites and cleared all user favorites.",
                "success",
            )
        else:
            if changed_count:
                log_activity(
                    f"Removed stale favorites for {changed_count} user(s) after restore {filename}"
                )
            flash(
                f"Backup restored from {filename}. Favorites mode: pruned invalid favorites.",
                "success",
            )
        restore_message = (
            f"Restored backup {filename} with compatibility warnings "
            f"(favorites_mode={mode})"
            if compatibility.warnings
            else f"Restored backup {filename} (favorites_mode={mode})"
        )
        log_activity(restore_message)
    else:
        for error in form.file.errors:
            flash(error, "error")
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
    fname = os.path.basename(filepath)
    try:
        compatibility = validate_backup_file_compatibility(filepath)
    except sqlite3.Error:
        flash("Invalid SQLite database.", "error")
        return redirect(url_for("admin.backups"))

    if not compatibility.compatible:
        details = "; ".join(compatibility.issues)
        current_app.logger.warning(
            "Restore preflight incompatibility detected for %s: %s",
            fname,
            details,
        )
        log_activity(
            f"Restore blocked due to compatibility errors for {fname}: {details}"
        )
        flash(
            "⚠️ Incompatible backup: this backup is missing critical database "
            "structures and cannot be restored safely.",
            "danger",
        )
        return redirect(url_for("admin.backups"))

    if compatibility.warnings:
        warning_details = "; ".join(compatibility.warnings)
        current_app.logger.warning(
            "Restore preflight compatibility warnings for %s: %s",
            fname,
            warning_details,
        )
        log_activity(
            f"Restore compatibility warnings detected for {fname}: {warning_details}"
        )

    restore_backup(filepath)
    ignore_values = {
        value.lower()
        for value in flask.request.values.getlist("ignore_favorites")
        if value
    }
    ignore_favorites = bool(ignore_values & {"1", "true", "on", "yes"})
    mode, changed_count = _apply_restore_favorites_mode(ignore_favorites)
    if compatibility.warnings:
        flash("Restored with compatibility warnings.", "warning")

    if mode == "ignored":
        log_activity(
            f"Cleared favorites for {changed_count} user(s) after restore {fname} (ignore_favorites=true)"
        )
        flash(
            f"Backup restored from {fname}. Favorites mode: ignored backup favorites and cleared all user favorites.",
            "success",
        )
    else:
        if changed_count:
            log_activity(
                f"Removed stale favorites for {changed_count} user(s) after restore {fname}"
            )
        flash(
            f"Backup restored from {fname}. Favorites mode: pruned invalid favorites.",
            "success",
        )
    restore_message = (
        f"Restored backup {fname} with compatibility warnings "
        f"(favorites_mode={mode})"
        if compatibility.warnings
        else f"Restored backup {fname} (favorites_mode={mode})"
    )
    log_activity(restore_message)
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
    form = ActivityLogFilterForm(meta={"csrf": False})
    user_choices = [(-1, "All Users"), (-2, "System Activity")]
    user_choices.extend(
        (user.id, user.email) for user in User.query.order_by(User.email)
    )
    form.user_id.choices = user_choices
    form.process(request.args)
    if form.user_id.data is None:
        form.user_id.data = -1

    query = ActivityLog.query.options(selectinload(ActivityLog.user))

    user_filter = form.user_id.data
    if user_filter is not None and user_filter != -1:
        if user_filter == -2:
            query = query.filter(ActivityLog.user_id.is_(None))
        else:
            query = query.filter(ActivityLog.user_id == user_filter)

    activity_filter = (form.activity.data or "").strip()
    if activity_filter:
        query = query.filter(ActivityLog.activity.ilike(f"%{activity_filter}%"))

    if form.start_date.data:
        start_dt = datetime.combine(form.start_date.data, datetime.min.time())
        query = query.filter(ActivityLog.timestamp >= start_dt)

    if form.end_date.data:
        end_dt = datetime.combine(form.end_date.data, datetime.max.time())
        query = query.filter(ActivityLog.timestamp <= end_dt)

    logs = query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template("admin/activity_logs.html", logs=logs, form=form)


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


@admin.route(
    "/controlpanel/import/<string:data_type>/example", methods=["GET"]
)
@login_required
def download_example(data_type):
    """Download an example CSV file for the given data type."""
    from flask import current_app, send_from_directory

    if not current_user.is_admin:
        abort(403)
    if data_type not in IMPORT_FILES:
        abort(404)
    directory = current_app.config["IMPORT_FILES_FOLDER"]
    filename = IMPORT_FILES[data_type]
    log_activity(f"Downloaded example import file for {data_type}")
    return send_from_directory(directory, filename, as_attachment=True)


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
            count = _import_csv(
                path, User, {"email": "email", "password": "password"}
            )
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

    retail_pop_price_setting = Setting.query.filter_by(
        name="RETAIL_POP_PRICE"
    ).first()
    if retail_pop_price_setting is None:
        retail_pop_price_setting = Setting(
            name="RETAIL_POP_PRICE", value="4.25"
        )
        db.session.add(retail_pop_price_setting)

    tz_setting = Setting.query.filter_by(name="DEFAULT_TIMEZONE").first()
    if tz_setting is None:
        tz_setting = Setting(name="DEFAULT_TIMEZONE", value="UTC")
        db.session.add(tz_setting)

    auto_setting = Setting.query.filter_by(name="AUTO_BACKUP_ENABLED").first()
    if auto_setting is None:
        auto_setting = Setting(name="AUTO_BACKUP_ENABLED", value="0")
        db.session.add(auto_setting)

    interval_value_setting = Setting.query.filter_by(
        name="AUTO_BACKUP_INTERVAL_VALUE"
    ).first()
    if interval_value_setting is None:
        interval_value_setting = Setting(
            name="AUTO_BACKUP_INTERVAL_VALUE", value="1"
        )
        db.session.add(interval_value_setting)

    interval_unit_setting = Setting.query.filter_by(
        name="AUTO_BACKUP_INTERVAL_UNIT"
    ).first()
    if interval_unit_setting is None:
        interval_unit_setting = Setting(
            name="AUTO_BACKUP_INTERVAL_UNIT", value="day"
        )
        db.session.add(interval_unit_setting)

    max_backups_setting = Setting.query.filter_by(name="MAX_BACKUPS").first()
    if max_backups_setting is None:
        max_backups_setting = Setting(name="MAX_BACKUPS", value="5")
        db.session.add(max_backups_setting)

    import_vendor_setting = Setting.query.filter_by(
        name=Setting.PURCHASE_IMPORT_VENDORS
    ).first()
    if import_vendor_setting is None:
        import_vendor_setting = Setting(
            name=Setting.PURCHASE_IMPORT_VENDORS,
            value=json.dumps(Setting.DEFAULT_PURCHASE_IMPORT_VENDORS),
        )
        db.session.add(import_vendor_setting)

    conversions_setting = Setting.query.filter_by(
        name="BASE_UNIT_CONVERSIONS"
    ).first()
    if conversions_setting is None:
        conversions_setting = Setting(
            name="BASE_UNIT_CONVERSIONS",
            value=serialize_conversion_setting(DEFAULT_BASE_UNIT_CONVERSIONS),
        )
        db.session.add(conversions_setting)

    db.session.commit()

    conversion_mapping = parse_conversion_setting(conversions_setting.value)
    receive_defaults = Setting.get_receive_location_defaults()
    enabled_import_vendors = Setting.get_enabled_purchase_import_vendors()
    retail_pop_price_value = retail_pop_price_setting.value or "0"
    try:
        retail_pop_price_decimal = Decimal(retail_pop_price_value)
    except (InvalidOperation, TypeError):
        retail_pop_price_decimal = Decimal("0")

    form = SettingsForm(
        gst_number=gst_setting.value,
        default_timezone=tz_setting.value,
        auto_backup_enabled=auto_setting.value == "1",
        auto_backup_interval_value=int(interval_value_setting.value),
        auto_backup_interval_unit=interval_unit_setting.value,
        max_backups=int(max_backups_setting.value),
        base_unit_mapping=conversion_mapping,
        receive_location_defaults=receive_defaults,
        purchase_import_vendors=enabled_import_vendors,
        retail_pop_price=retail_pop_price_decimal,
    )
    if form.validate_on_submit():
        conversion_updates = {}
        has_conversion_error = False
        for unit, _, field in form.iter_base_unit_conversions():
            target = field.data
            if target not in get_allowed_target_units(unit):
                field.errors.append("Unsupported conversion selected.")
                has_conversion_error = True
            else:
                conversion_updates[unit] = target

        for unit in DEFAULT_BASE_UNIT_CONVERSIONS:
            conversion_updates.setdefault(unit, unit)

        if has_conversion_error:
            return render_template("admin/settings.html", form=form)

        enabled_import_vendors = [
            label
            for label, field in form.iter_purchase_import_vendors()
            if field.data
        ]
        if not enabled_import_vendors:
            form.enable_sysco_imports.errors.append(
                "Select at least one vendor to enable for imports."
            )
            return render_template("admin/settings.html", form=form)

        receive_location_updates = {}
        for department, _, field_name in PURCHASE_RECEIVE_DEPARTMENT_CONFIG:
            field = getattr(form, field_name)
            if field.data:
                receive_location_updates[department] = field.data

        gst_setting.value = form.gst_number.data or ""
        tz_setting.value = form.default_timezone.data or "UTC"
        auto_setting.value = "1" if form.auto_backup_enabled.data else "0"
        interval_value_setting.value = str(
            form.auto_backup_interval_value.data
        )
        interval_unit_setting.value = form.auto_backup_interval_unit.data
        max_backups_setting.value = str(form.max_backups.data)
        conversions_setting.value = serialize_conversion_setting(
            conversion_updates
        )
        if form.retail_pop_price.data is None:
            retail_pop_price_setting.value = ""
        else:
            retail_pop_price_setting.value = format(
                form.retail_pop_price.data, ".2f"
            )
        Setting.set_enabled_purchase_import_vendors(enabled_import_vendors)
        Setting.set_receive_location_defaults(receive_location_updates)
        db.session.commit()
        import app

        app.GST = gst_setting.value
        app.RETAIL_POP_PRICE = (
            retail_pop_price_setting.value or "0.00"
        )
        app.DEFAULT_TIMEZONE = tz_setting.value
        current_app.config["AUTO_BACKUP_ENABLED"] = (
            form.auto_backup_enabled.data
        )
        current_app.config["AUTO_BACKUP_INTERVAL_VALUE"] = (
            form.auto_backup_interval_value.data
        )
        current_app.config["AUTO_BACKUP_INTERVAL_UNIT"] = (
            form.auto_backup_interval_unit.data
        )
        current_app.config["MAX_BACKUPS"] = form.max_backups.data
        current_app.config["AUTO_BACKUP_INTERVAL"] = (
            form.auto_backup_interval_value.data
            * UNIT_SECONDS[form.auto_backup_interval_unit.data]
        )
        current_app.config["RETAIL_POP_PRICE"] = app.RETAIL_POP_PRICE
        conversion_mapping = parse_conversion_setting(conversions_setting.value)
        app.BASE_UNIT_CONVERSIONS = conversion_mapping
        current_app.config["BASE_UNIT_CONVERSIONS"] = conversion_mapping
        start_auto_backup_thread(current_app._get_current_object())
        flash("Settings updated.", "success")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", form=form)


@admin.route("/controlpanel/terminal-sales-mappings", methods=["GET", "POST"])
@login_required
def terminal_sales_mappings():
    """Allow admins to remove stored terminal sales aliases."""

    if not current_user.is_admin:
        abort(403)

    product_aliases = (
        TerminalSaleProductAlias.query.options(
            selectinload(TerminalSaleProductAlias.product)
        )
        .order_by(TerminalSaleProductAlias.source_name)
        .all()
    )
    location_aliases = (
        TerminalSaleLocationAlias.query.options(
            selectinload(TerminalSaleLocationAlias.location)
        )
        .order_by(TerminalSaleLocationAlias.source_name)
        .all()
    )

    product_form = TerminalSalesMappingDeleteForm(prefix="product")
    location_form = TerminalSalesMappingDeleteForm(prefix="location")

    product_form.selected_ids.choices = [
        (alias.id, alias.source_name) for alias in product_aliases
    ]
    location_form.selected_ids.choices = [
        (alias.id, alias.source_name) for alias in location_aliases
    ]

    if product_form.delete_all.data or product_form.delete_selected.data:
        if product_form.validate_on_submit():
            deleted_count = 0
            if product_form.delete_all.data:
                deleted_count = TerminalSaleProductAlias.query.delete()
            else:
                selected_ids = product_form.selected_ids.data or []
                if selected_ids:
                    deleted_count = (
                        TerminalSaleProductAlias.query.filter(
                            TerminalSaleProductAlias.id.in_(selected_ids)
                        ).delete(synchronize_session=False)
                    )
                else:
                    flash("Select at least one product mapping to remove.", "warning")
            if deleted_count:
                db.session.commit()
                action = (
                    "all terminal sales product mappings"
                    if product_form.delete_all.data
                    else f"{deleted_count} terminal sales product mapping"
                )
                if deleted_count > 1 and not product_form.delete_all.data:
                    action += "s"
                log_activity(f"Deleted {action} via admin panel")
                flash(
                    f"Removed {deleted_count} product mapping"
                    f"{'s' if deleted_count != 1 else ''}.",
                    "success",
                )
            elif product_form.delete_all.data:
                flash("There were no product mappings to remove.", "info")
            return redirect(url_for("admin.terminal_sales_mappings"))
        flash("Unable to process the request. Please try again.", "danger")
        return redirect(url_for("admin.terminal_sales_mappings"))

    if location_form.delete_all.data or location_form.delete_selected.data:
        if location_form.validate_on_submit():
            deleted_count = 0
            if location_form.delete_all.data:
                deleted_count = TerminalSaleLocationAlias.query.delete()
            else:
                selected_ids = location_form.selected_ids.data or []
                if selected_ids:
                    deleted_count = (
                        TerminalSaleLocationAlias.query.filter(
                            TerminalSaleLocationAlias.id.in_(selected_ids)
                        ).delete(synchronize_session=False)
                    )
                else:
                    flash(
                        "Select at least one location mapping to remove.",
                        "warning",
                    )
            if deleted_count:
                db.session.commit()
                action = (
                    "all terminal sales location mappings"
                    if location_form.delete_all.data
                    else f"{deleted_count} terminal sales location mapping"
                )
                if deleted_count > 1 and not location_form.delete_all.data:
                    action += "s"
                log_activity(f"Deleted {action} via admin panel")
                flash(
                    f"Removed {deleted_count} location mapping"
                    f"{'s' if deleted_count != 1 else ''}.",
                    "success",
                )
            elif location_form.delete_all.data:
                flash("There were no location mappings to remove.", "info")
            return redirect(url_for("admin.terminal_sales_mappings"))
        flash("Unable to process the request. Please try again.", "danger")
        return redirect(url_for("admin.terminal_sales_mappings"))

    return render_template(
        "admin/terminal_sales_mappings.html",
        product_form=product_form,
        location_form=location_form,
        product_aliases=product_aliases,
        location_aliases=location_aliases,
    )


@admin.route("/controlpanel/sales-imports", methods=["GET"])
@login_required
def sales_imports():
    """Render staged POS sales imports for admin review."""

    if not current_user.is_admin:
        abort(403)

    status_filter = (request.args.get("status") or "").strip().lower()

    query = PosSalesImport.query.options(
        selectinload(PosSalesImport.locations),
        selectinload(PosSalesImport.rows),
    ).order_by(
        PosSalesImport.received_at.desc(),
        PosSalesImport.id.desc(),
    )
    if status_filter:
        query = query.filter(PosSalesImport.status == status_filter)

    imports = query.limit(200).all()
    available_statuses = [
        "pending",
        "needs_mapping",
        "approved",
        "reversed",
        "deleted",
        "failed",
    ]

    return render_template(
        "admin/sales_imports.html",
        imports=imports,
        status_filter=status_filter,
        available_statuses=available_statuses,
    )


@admin.route("/controlpanel/sales-imports/<int:import_id>", methods=["GET", "POST"])
@login_required
def sales_import_detail(import_id: int):
    """Render location and row-level detail for a staged POS sales import."""

    if not current_user.is_admin:
        abort(403)

    sales_import = (
        PosSalesImport.query.options(
            selectinload(PosSalesImport.locations)
            .selectinload(PosSalesImportLocation.rows)
            .selectinload(PosSalesImportRow.product),
            selectinload(PosSalesImport.locations).selectinload(PosSalesImportLocation.location),
            selectinload(PosSalesImport.approver),
            selectinload(PosSalesImport.reverser),
        )
        .filter(PosSalesImport.id == import_id)
        .first_or_404()
    )

    def _refresh_import_mapping_status() -> tuple[int, int]:
        unresolved_location_count = sum(
            1 for location in sales_import.locations if location.location_id is None
        )
        unresolved_row_count = sum(
            1
            for location in sales_import.locations
            for row in location.rows
            if row.product_id is None
        )
        next_status = (
            "needs_mapping"
            if unresolved_location_count or unresolved_row_count
            else "pending"
        )
        if sales_import.status != next_status:
            sales_import.status = next_status
            db.session.commit()
        return unresolved_location_count, unresolved_row_count

    def _apply_auto_mappings() -> bool:
        changed = False

        exact_location_lookup = {
            (location.name or "").strip().casefold(): location.id
            for location in Location.query.all()
            if location.name
        }
        exact_product_lookup = {
            (product.name or "").strip().casefold(): product.id
            for product in Product.query.all()
            if product.name
        }

        location_alias_lookup = {
            alias.normalized_name: alias.location_id
            for alias in TerminalSaleLocationAlias.query.all()
            if alias.normalized_name and alias.location_id
        }
        product_alias_lookup = {
            alias.normalized_name: alias.product_id
            for alias in TerminalSaleProductAlias.query.all()
            if alias.normalized_name and alias.product_id
        }

        normalized_location_lookup = {
            normalize_pos_alias(location.name or ""): location.id
            for location in Location.query.all()
            if location.name
        }
        normalized_product_lookup = {
            normalize_pos_alias(product.name or ""): product.id
            for product in Product.query.all()
            if product.name
        }

        for location in sales_import.locations:
            if location.location_id is None:
                exact_key = (location.source_location_name or "").strip().casefold()
                normalized_key = location.normalized_location_name or normalize_pos_alias(
                    location.source_location_name or ""
                )
                matched_location_id = exact_location_lookup.get(exact_key)
                if matched_location_id is None and normalized_key:
                    matched_location_id = location_alias_lookup.get(normalized_key)
                if matched_location_id is None and normalized_key:
                    matched_location_id = normalized_location_lookup.get(normalized_key)
                if matched_location_id is not None:
                    location.location_id = matched_location_id
                    changed = True

            for row in location.rows:
                if row.product_id is not None:
                    continue
                exact_key = (row.source_product_name or "").strip().casefold()
                normalized_key = row.normalized_product_name or normalize_pos_alias(
                    row.source_product_name or ""
                )
                matched_product_id = exact_product_lookup.get(exact_key)
                if matched_product_id is None and normalized_key:
                    matched_product_id = product_alias_lookup.get(normalized_key)
                if matched_product_id is None and normalized_key:
                    matched_product_id = normalized_product_lookup.get(normalized_key)
                if matched_product_id is not None:
                    row.product_id = matched_product_id
                    changed = True

        return changed

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        selected_location_id = request.form.get("selected_location_id", type=int)

        if action == "map_location":
            location_import_id = request.form.get("location_import_id", type=int)
            target_location_id = request.form.get("target_location_id", type=int)
            location_record = next(
                (loc for loc in sales_import.locations if loc.id == location_import_id),
                None,
            )
            if not location_record:
                flash("Unable to find the selected import location.", "danger")
            elif not target_location_id:
                flash("Select a location to map.", "warning")
            else:
                normalized_key = location_record.normalized_location_name
                for scoped_location in sales_import.locations:
                    if scoped_location.normalized_location_name == normalized_key:
                        scoped_location.location_id = target_location_id

                alias = TerminalSaleLocationAlias.query.filter_by(
                    normalized_name=normalized_key
                ).first()
                if alias is None:
                    alias = TerminalSaleLocationAlias(
                        source_name=location_record.source_location_name,
                        normalized_name=normalized_key,
                        location_id=target_location_id,
                    )
                    db.session.add(alias)
                else:
                    alias.source_name = location_record.source_location_name
                    alias.location_id = target_location_id
                db.session.commit()
                flash("Location mapping saved.", "success")

        elif action == "create_location":
            location_import_id = request.form.get("location_import_id", type=int)
            new_location_name = (request.form.get("new_location_name") or "").strip()
            location_record = next(
                (loc for loc in sales_import.locations if loc.id == location_import_id),
                None,
            )
            if not location_record:
                flash("Unable to find the selected import location.", "danger")
            elif not new_location_name:
                flash("Enter a new location name before creating.", "warning")
            else:
                existing = Location.query.filter_by(name=new_location_name).first()
                if existing:
                    created_location = existing
                else:
                    created_location = Location(name=new_location_name)
                    db.session.add(created_location)
                    db.session.flush()

                normalized_key = location_record.normalized_location_name
                for scoped_location in sales_import.locations:
                    if scoped_location.normalized_location_name == normalized_key:
                        scoped_location.location_id = created_location.id

                alias = TerminalSaleLocationAlias.query.filter_by(
                    normalized_name=normalized_key
                ).first()
                if alias is None:
                    alias = TerminalSaleLocationAlias(
                        source_name=location_record.source_location_name,
                        normalized_name=normalized_key,
                        location_id=created_location.id,
                    )
                    db.session.add(alias)
                else:
                    alias.source_name = location_record.source_location_name
                    alias.location_id = created_location.id
                db.session.commit()
                flash("Location created and mapping saved.", "success")

        elif action == "map_product":
            row_id = request.form.get("row_id", type=int)
            target_product_id = request.form.get("target_product_id", type=int)
            row_record = next(
                (
                    row
                    for location in sales_import.locations
                    for row in location.rows
                    if row.id == row_id
                ),
                None,
            )
            if not row_record:
                flash("Unable to find the selected import row.", "danger")
            elif not target_product_id:
                flash("Select a product to map.", "warning")
            else:
                normalized_key = row_record.normalized_product_name
                for scoped_row in sales_import.rows:
                    if scoped_row.normalized_product_name == normalized_key:
                        scoped_row.product_id = target_product_id

                alias = TerminalSaleProductAlias.query.filter_by(
                    normalized_name=normalized_key
                ).first()
                if alias is None:
                    alias = TerminalSaleProductAlias(
                        source_name=row_record.source_product_name,
                        normalized_name=normalized_key,
                        product_id=target_product_id,
                    )
                    db.session.add(alias)
                else:
                    alias.source_name = row_record.source_product_name
                    alias.product_id = target_product_id
                db.session.commit()
                flash("Product mapping saved.", "success")

        elif action == "create_product":
            row_id = request.form.get("row_id", type=int)
            new_product_name = (request.form.get("new_product_name") or "").strip()
            row_record = next(
                (
                    row
                    for location in sales_import.locations
                    for row in location.rows
                    if row.id == row_id
                ),
                None,
            )
            if not row_record:
                flash("Unable to find the selected import row.", "danger")
            elif not new_product_name:
                flash("Enter a new product name before creating.", "warning")
            else:
                existing = Product.query.filter_by(name=new_product_name).first()
                if existing:
                    created_product = existing
                else:
                    created_product = Product(
                        name=new_product_name,
                        price=0.0,
                        invoice_sale_price=0,
                        cost=0.0,
                    )
                    db.session.add(created_product)
                    db.session.flush()

                normalized_key = row_record.normalized_product_name
                for scoped_row in sales_import.rows:
                    if scoped_row.normalized_product_name == normalized_key:
                        scoped_row.product_id = created_product.id

                alias = TerminalSaleProductAlias.query.filter_by(
                    normalized_name=normalized_key
                ).first()
                if alias is None:
                    alias = TerminalSaleProductAlias(
                        source_name=row_record.source_product_name,
                        normalized_name=normalized_key,
                        product_id=created_product.id,
                    )
                    db.session.add(alias)
                else:
                    alias.source_name = row_record.source_product_name
                    alias.product_id = created_product.id
                db.session.commit()
                flash("Product created and mapping saved.", "success")

        elif action == "refresh_auto_mapping":
            if _apply_auto_mappings():
                db.session.commit()
                flash("Applied latest automatic mappings.", "success")
            else:
                flash("No additional automatic mappings were found.", "info")

        return redirect(
            url_for(
                "admin.sales_import_detail",
                import_id=sales_import.id,
                location_id=selected_location_id,
            )
        )

    if _apply_auto_mappings():
        db.session.commit()

    unresolved_location_count, unresolved_row_count = _refresh_import_mapping_status()

    selected_location_id = request.args.get("location_id", type=int)
    selected_location = None
    if selected_location_id is not None:
        selected_location = next(
            (
                location
                for location in sales_import.locations
                if location.id == selected_location_id
            ),
            None,
        )
    if selected_location is None and sales_import.locations:
        selected_location = sales_import.locations[0]

    import_totals = {
        "quantity": sum(float(loc.total_quantity or 0.0) for loc in sales_import.locations),
        "net_inc": sum(float(loc.net_inc or 0.0) for loc in sales_import.locations),
        "discounts_abs": sum(
            float(loc.discounts_abs or 0.0) for loc in sales_import.locations
        ),
        "computed_total": sum(
            float(loc.computed_total or 0.0) for loc in sales_import.locations
        ),
    }

    location_errors: dict[int, list[str]] = {}
    row_errors: dict[int, list[str]] = {}
    for location in sales_import.locations:
        errors: list[str] = []
        if location.location_id is None:
            errors.append("Location is not mapped.")
        location_errors[location.id] = errors

        for row in location.rows:
            row_validation_errors: list[str] = []
            if row.product_id is None:
                row_validation_errors.append("Product is not mapped.")
            if row.is_zero_quantity:
                row_validation_errors.append(
                    "Quantity is zero; treat as informational and exclude from stock operations."
                )
            row_errors[row.id] = row_validation_errors

    return render_template(
        "admin/sales_import_detail.html",
        sales_import=sales_import,
        selected_location=selected_location,
        import_totals=import_totals,
        location_errors=location_errors,
        row_errors=row_errors,
        locations=Location.query.order_by(Location.name).all(),
        products=Product.query.order_by(Product.name).all(),
        unresolved_location_count=unresolved_location_count,
        unresolved_row_count=unresolved_row_count,
    )


@admin.route("/controlpanel/vendor-item-aliases", methods=["GET", "POST"])
@admin.route(
    "/controlpanel/vendor-item-aliases/<int:alias_id>/edit", methods=["GET", "POST"]
)
@login_required
def vendor_item_aliases(alias_id: int | None = None):
    """Allow admins to manage vendor item alias mappings."""

    if not current_user.is_admin:
        abort(403)

    alias_obj = db.session.get(VendorItemAlias, alias_id) if alias_id else None
    form = VendorItemAliasForm(obj=alias_obj)
    delete_form = DeleteForm()

    aliases = (
        VendorItemAlias.query.options(
            selectinload(VendorItemAlias.vendor),
            selectinload(VendorItemAlias.item),
            selectinload(VendorItemAlias.item_unit),
        )
        .order_by(VendorItemAlias.vendor_id, VendorItemAlias.vendor_sku)
        .all()
    )

    if form.validate_on_submit():
        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash("Select a valid vendor before saving the alias.", "danger")
            return redirect(url_for("admin.vendor_item_aliases"))

        unit_id = form.item_unit_id.data or None
        if unit_id == 0:
            unit_id = None

        default_cost = (
            float(form.default_cost.data)
            if form.default_cost.data is not None
            else None
        )

        if alias_obj:
            alias_obj.vendor_id = vendor.id
            alias_obj.item_id = form.item_id.data
            alias_obj.item_unit_id = unit_id
            alias_obj.vendor_sku = form.vendor_sku.data or None
            alias_obj.vendor_description = form.vendor_description.data or None
            alias_obj.normalized_description = normalize_vendor_alias_text(
                alias_obj.vendor_description or alias_obj.vendor_sku
            )
            alias_obj.pack_size = form.pack_size.data or None
            alias_obj.default_cost = default_cost
            alias = alias_obj
        else:
            alias = update_or_create_vendor_alias(
                vendor=vendor,
                item_id=form.item_id.data,
                item_unit_id=unit_id,
                vendor_sku=form.vendor_sku.data or None,
                vendor_description=form.vendor_description.data or None,
                pack_size=form.pack_size.data or None,
                default_cost=default_cost,
            )
            db.session.add(alias)

        db.session.commit()
        log_activity(
            f"Saved vendor alias for vendor {vendor.first_name} {vendor.last_name}"
        )
        flash("Vendor alias saved successfully.", "success")
        return redirect(url_for("admin.vendor_item_aliases"))

    return render_template(
        "admin/vendor_item_aliases.html",
        form=form,
        delete_form=delete_form,
        aliases=aliases,
        editing_alias=alias_obj,
    )


@admin.route(
    "/controlpanel/vendor-item-aliases/<int:alias_id>/delete",
    methods=["POST"],
)
@login_required
def delete_vendor_item_alias(alias_id: int):
    if not current_user.is_admin:
        abort(403)

    form = DeleteForm()
    if not form.validate_on_submit():
        flash("Unable to process the delete request.", "danger")
        return redirect(url_for("admin.vendor_item_aliases"))

    alias = db.session.get(VendorItemAlias, alias_id)
    if alias is None:
        flash("Vendor alias not found.", "warning")
        return redirect(url_for("admin.vendor_item_aliases"))

    db.session.delete(alias)
    db.session.commit()
    log_activity("Deleted a vendor item alias via admin panel")
    flash("Vendor alias deleted.", "success")
    return redirect(url_for("admin.vendor_item_aliases"))
