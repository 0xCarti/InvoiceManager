import os
from dotenv import load_dotenv
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bootstrap import Bootstrap
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash
from datetime import timedelta

load_dotenv()
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
socketio = None
GST = 0


@login_manager.user_loader
def load_user(user_id):
    """Retrieve a user by ID for Flask-Login."""
    from app.models import User
    return db.session.get(User, int(user_id))


def create_admin_user():
    """Ensure an admin user exists for the application."""
    from app.models import User
    # Check if any admin exists
    admin_exists = User.query.filter_by(is_admin=True).first()
    if not admin_exists:

        # Create an admin user
        admin_email = os.getenv('ADMIN_EMAIL')
        raw_password = os.getenv('ADMIN_PASS')
        if raw_password is None:
            raise RuntimeError('ADMIN_PASS environment variable not set')
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
    global socketio, GST
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
    )
    # Use absolute paths so that changing the working directory after app
    # creation does not break file references. This occurs in the test suite
    # which creates the app in a temporary directory and then changes back to
    # the original working directory.  Building the paths here ensures they
    # always point to the intended location.

    base_dir = os.getcwd()
    db_path = os.path.join(base_dir, 'inventory.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'uploads')
    app.config['BACKUP_FOLDER'] = os.path.join(base_dir, 'backups')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['BACKUP_FOLDER'], exist_ok=True)
    GST = os.getenv('GST')
    if '--demo' in args:
        app.config['DEMO'] = True
    else:
        app.config['DEMO'] = False

    db.init_app(app)
    from flask_migrate import Migrate
    Migrate(app, db)
    login_manager.init_app(app)
    Bootstrap(app)
    socketio = SocketIO(app)

    @app.context_processor
    def inject_gst():
        """Inject the GST constant into all templates."""
        return dict(GST=GST)

    with app.app_context():
        from app.routes import auth_routes
        from app.routes.auth_routes import auth, admin
        from app.routes.main_routes import main
        from app.routes.location_routes import location
        from app.routes.item_routes import item
        from app.routes.transfer_routes import transfer
        from app.routes.customer_routes import customer
        from app.routes.invoice_routes import invoice
        from app.routes.product_routes import product
        from app.routes.purchase_routes import purchase
        from app.routes.report_routes import report
        from app.routes.vendor_routes import vendor
        from app.routes.event_routes import event
        from app.routes.glcode_routes import glcode_bp
        from app.models import User

        app.register_blueprint(auth, url_prefix='/auth')
        app.register_blueprint(main)
        app.register_blueprint(location)
        app.register_blueprint(item)
        app.register_blueprint(transfer)
        app.register_blueprint(admin)
        app.register_blueprint(customer)
        app.register_blueprint(invoice)
        app.register_blueprint(product)
        app.register_blueprint(purchase)
        app.register_blueprint(report)
        app.register_blueprint(vendor)
        app.register_blueprint(event)
        app.register_blueprint(glcode_bp)

        db.create_all()
        create_admin_user()
        CSRFProtect(app)

    return app, socketio
