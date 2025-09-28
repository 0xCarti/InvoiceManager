import os
import secrets
import sys
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, Response, g, render_template, request
from flask_bootstrap import Bootstrap
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from werkzeug.security import generate_password_hash

load_dotenv()
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
storage_uri = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
limiter = Limiter(key_func=get_remote_address, storage_uri=storage_uri)
socketio = None


def _get_bool_env(var_name: str, default: bool = False) -> bool:
    """Return a boolean environment variable value."""

    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_CSP_TEMPLATE = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' https://cdn.jsdelivr.net 'nonce-{nonce}'; "
    "font-src 'self' data:; "
    "connect-src 'self' wss: https://cdn.jsdelivr.net; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "object-src 'none'; "
    "base-uri 'self'"
)
GST = ""
DEFAULT_TIMEZONE = "UTC"
NAV_LINKS = {
    "transfer.view_transfers": "Transfers",
    "item.view_items": "Items",
    "locations.view_locations": "Locations",
    "product.view_products": "Products",
    "spoilage.view_spoilage": "Spoilage",
    "glcode.view_gl_codes": "GL Codes",
    "purchase.view_purchase_orders": "Purchase Orders",
    "purchase.view_purchase_invoices": "Purchase Invoices",
    "customer.view_customers": "Customers",
    "vendor.view_vendors": "Vendors",
    "invoice.view_invoices": "Invoices",
    "event.view_events": "Events",
    "admin.users": "Control Panel",
    "admin.backups": "Backups",
    "admin.settings": "Settings",
    "admin.import_page": "Data Imports",
    "admin.activity_logs": "Activity Logs",
    "admin.system_info": "System Info",
}


@login_manager.user_loader
def load_user(user_id):
    """Retrieve a user by ID for Flask-Login."""
    from app.models import User

    return db.session.get(User, int(user_id))


def create_admin_user():
    """Ensure an admin user exists for the application."""
    from app.models import User

    # Ensure all tables are created before querying. This guards against
    # OperationalError exceptions when the database has not been
    # initialised yet (e.g. during first run or tests).
    db.create_all()

    # Check if any admin exists
    admin_exists = User.query.filter_by(is_admin=True).first()
    if not admin_exists:

        # Create an admin user
        admin_email = os.getenv("ADMIN_EMAIL")
        raw_password = os.getenv("ADMIN_PASS")
        if raw_password is None:
            raise RuntimeError("ADMIN_PASS environment variable not set")
        admin_password = generate_password_hash(raw_password)
        admin_user = User(
            email=admin_email,
            password=admin_password,
            is_admin=True,
            active=True,
        )

        db.session.add(admin_user)
        db.session.commit()
        print("Admin user created.")


def create_app(args: list):
    """Application factory used by Flask."""
    global socketio, GST, DEFAULT_TIMEZONE
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    default_secure_cookies = "--demo" not in args
    session_cookie_secure = _get_bool_env(
        "SESSION_COOKIE_SECURE", default=default_secure_cookies
    )
    enforce_https = _get_bool_env("ENFORCE_HTTPS", default=False)
    app.config["ENFORCE_HTTPS"] = enforce_https
    app.config.update(
        SESSION_COOKIE_SECURE=session_cookie_secure,
        REMEMBER_COOKIE_SECURE=session_cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    )
    app.config["START_TIME"] = datetime.utcnow()
    # Use absolute paths so that changing the working directory after app
    # creation does not break file references. This occurs in the test suite
    # which creates the app in a temporary directory and then changes back to
    # the original working directory.  Building the paths here ensures they
    # always point to the intended location.

    base_dir = os.getcwd()
    repo_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir)
    )
    # Allow overriding the database location via the DATABASE_PATH environment
    # variable.  This is useful for container deployments where the database
    # may reside in a mounted volume.  If the provided path is a directory,
    # store the SQLite file inside that directory.
    default_db_path = os.path.join(base_dir, "inventory.db")
    db_path = os.getenv("DATABASE_PATH", default_db_path)
    if os.path.isdir(db_path):
        db_path = os.path.join(db_path, "inventory.db")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["UPLOAD_FOLDER"] = os.path.join(base_dir, "uploads")
    app.config["BACKUP_FOLDER"] = os.path.join(base_dir, "backups")
    app.config["IMPORT_FILES_FOLDER"] = os.path.join(repo_dir, "import_files")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["BACKUP_FOLDER"], exist_ok=True)
    os.makedirs(app.config["IMPORT_FILES_FOLDER"], exist_ok=True)

    if "--demo" in args:
        app.config["DEMO"] = True
    else:
        app.config["DEMO"] = False

    db.init_app(app)
    from flask_migrate import Migrate

    Migrate(app, db)
    login_manager.init_app(app)
    if app.config.get("TESTING"):
        app.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(app)
    Bootstrap(app)
    socketio = SocketIO(app)

    from flask_login import current_user

    def format_datetime(value, fmt="%Y-%m-%d %H:%M:%S"):
        if value is None:
            return ""
        tz_name = getattr(current_user, "timezone", None)
        if not tz_name:
            tz_name = DEFAULT_TIMEZONE or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time())
            value = value.replace(tzinfo=dt_timezone.utc)
        elif value.tzinfo is None:
            value = value.replace(tzinfo=dt_timezone.utc)
        if sys.platform.startswith("win"):
            fmt = fmt.replace("%-", "%#")
        return value.astimezone(tz).strftime(fmt)

    app.jinja_env.filters["format_datetime"] = format_datetime

    @app.context_processor
    def inject_gst():
        """Inject the GST constant into all templates."""
        return dict(GST=GST)

    @app.context_processor
    def inject_nav_links():
        """Provide navigation labels to templates."""
        return dict(NAV_LINKS=NAV_LINKS)

    @app.context_processor
    def inject_pagination_sizes():
        """Expose pagination size options to all templates."""
        from app.utils.pagination import PAGINATION_SIZES

        return {"PAGINATION_SIZES": PAGINATION_SIZES}

    @app.before_request
    def set_csp_nonce():
        """Generate a nonce for inline scripts allowed by the CSP."""

        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def apply_security_headers(response):
        """Attach standard security headers to every response."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.is_secure or app.config.get("ENFORCE_HTTPS", False):
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )
        nonce = getattr(g, "csp_nonce", "")
        if not nonce:
            nonce = secrets.token_urlsafe(16)
            g.csp_nonce = nonce
        csp_template = app.config.get("CONTENT_SECURITY_POLICY_TEMPLATE")
        if csp_template is None:
            csp_template = app.config.get(
                "CONTENT_SECURITY_POLICY", DEFAULT_CSP_TEMPLATE
            )
        try:
            csp = csp_template.format(nonce=nonce)
        except Exception:
            csp = csp_template
        response.headers.setdefault("Content-Security-Policy", csp)
        return response

    @app.context_processor
    def inject_csp_nonce():
        """Expose the CSP nonce to templates for inline scripts."""

        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.before_request
    def block_http_options():
        """Return a 405 for HTTP OPTIONS requests to reduce information leakage."""
        if request.method == "OPTIONS":
            return Response(status=405)

    @app.route("/.well-known/security.txt")
    def security_txt():
        """Provide contact details for responsible disclosure."""
        contact_email = os.getenv("SECURITY_CONTACT_EMAIL") or os.getenv(
            "ADMIN_EMAIL", "security@example.com"
        )
        policy_url = os.getenv("SECURITY_POLICY_URL", "https://example.com/security")
        lines = [
            f"Contact: mailto:{contact_email}",
            f"Policy: {policy_url}",
            "Preferred-Languages: en",
        ]
        return Response("\n".join(lines) + "\n", mimetype="text/plain")

    with app.app_context():
        # Ensure models are imported and the database schema is created on
        # application start.  This allows the app to run even if migrations
        # have not been executed yet, avoiding "no such table" errors.
        from . import models  # noqa: F401

        db.create_all()

        from app.routes.auth_routes import admin, auth
        from app.routes.customer_routes import customer
        from app.routes.event_routes import event
        from app.routes.glcode_routes import glcode_bp
        from app.routes.invoice_routes import invoice
        from app.routes.item_routes import item
        from app.routes.location_routes import location
        from app.routes.main_routes import main
        from app.routes.note_routes import notes
        from app.routes.product_routes import product
        from app.routes.purchase_routes import purchase
        from app.routes.report_routes import report
        from app.routes.spoilage_routes import spoilage
        from app.routes.transfer_routes import transfer
        from app.routes.vendor_routes import vendor

        app.register_blueprint(auth, url_prefix="/auth")
        app.register_blueprint(main)
        app.register_blueprint(location)
        app.register_blueprint(item)
        app.register_blueprint(transfer)
        app.register_blueprint(spoilage)
        app.register_blueprint(admin)
        app.register_blueprint(customer)
        app.register_blueprint(invoice)
        app.register_blueprint(product)
        app.register_blueprint(notes)
        app.register_blueprint(purchase)
        app.register_blueprint(report)
        app.register_blueprint(vendor)
        app.register_blueprint(event)
        app.register_blueprint(glcode_bp)
        from sqlalchemy.exc import OperationalError

        from app.models import Setting

        try:
            setting = Setting.query.filter_by(name="GST").first()
            if setting is not None:
                GST = setting.value

            tz_setting = Setting.query.filter_by(
                name="DEFAULT_TIMEZONE"
            ).first()
            if tz_setting is not None and tz_setting.value:
                DEFAULT_TIMEZONE = tz_setting.value

            auto_setting = Setting.query.filter_by(
                name="AUTO_BACKUP_ENABLED"
            ).first()
            interval_value_setting = Setting.query.filter_by(
                name="AUTO_BACKUP_INTERVAL_VALUE"
            ).first()
            interval_unit_setting = Setting.query.filter_by(
                name="AUTO_BACKUP_INTERVAL_UNIT"
            ).first()
            max_backups_setting = Setting.query.filter_by(
                name="MAX_BACKUPS"
            ).first()

            from app.utils.backup import UNIT_SECONDS, start_auto_backup_thread

            app.config["AUTO_BACKUP_ENABLED"] = (
                auto_setting.value == "1" if auto_setting else False
            )
            app.config["AUTO_BACKUP_INTERVAL_VALUE"] = (
                int(interval_value_setting.value)
                if interval_value_setting and interval_value_setting.value
                else 1
            )
            app.config["AUTO_BACKUP_INTERVAL_UNIT"] = (
                interval_unit_setting.value
                if interval_unit_setting and interval_unit_setting.value
                else "day"
            )
            app.config["MAX_BACKUPS"] = (
                int(max_backups_setting.value)
                if max_backups_setting and max_backups_setting.value
                else 5
            )
            app.config["AUTO_BACKUP_INTERVAL"] = (
                app.config["AUTO_BACKUP_INTERVAL_VALUE"]
                * UNIT_SECONDS[app.config["AUTO_BACKUP_INTERVAL_UNIT"]]
            )
            start_auto_backup_thread(app)
        except OperationalError:
            pass

        CSRFProtect(app)

        @app.errorhandler(CSRFError)
        def handle_csrf_error(error):
            """Render a helpful page when CSRF validation fails."""
            return (
                render_template(
                    "errors/csrf_error.html",
                    reason=error.description,
                ),
                400,
            )

    return app, socketio
