from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
import os

from app.forms import (
    LoginForm,
    UserForm,
    SignupForm,
    CreateBackupForm,
    RestoreBackupForm,
    ChangePasswordForm,
    SetPasswordForm,
    ImportForm,
)

from app.models import (
    User,
    db,
    Transfer,
    Invoice,
    ActivityLog,
    Location,
    Item,
    Product,
    ProductRecipeItem,
    ItemUnit,
    GLCode,
    Customer,
    Vendor,
)
from app.utils.activity import log_activity
from app.utils.backup import create_backup, restore_backup
from app.utils.imports import (
    _import_csv,
    _import_items,
    _import_locations,
    _import_products,
)

auth = Blueprint('auth', __name__)
admin = Blueprint('admin', __name__)

IMPORT_FILES = {
    'locations': 'example_locations.csv',
    'products': 'example_products.csv',
    'gl_codes': 'example_gl_codes.csv',
    'items': 'example_items.csv',
    'customers': 'example_customers.csv',
    'vendors': 'example_vendors.csv',
    'users': 'example_users.csv',
}


@auth.route('/login', methods=['GET', 'POST'])
def login():
    """Authenticate a user and start their session."""
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash('Please check your login details and try again.')
            return redirect(url_for('auth.login'))
        elif not user.active:
            flash('Please contact system admin to activate account.')
            return redirect(url_for('auth.login'))

        login_user(user)
        log_activity('Logged in', user.id)
        return redirect(url_for('transfer.view_transfers'))

    from run import app

    return render_template('auth/login.html', form=form, demo=app.config['DEMO'])


@auth.route('/logout')
@login_required
def logout():
    """Log the current user out."""
    user_id = current_user.id
    logout_user()
    log_activity('Logged out', user_id)
    return redirect(url_for('auth.login'))


@auth.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Allow the current user to change their password."""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password, form.current_password.data):
            flash('Current password incorrect.', 'danger')
        else:
            current_user.password = generate_password_hash(form.new_password.data)
            db.session.commit()
            flash('Password updated.', 'success')
            return redirect(url_for('auth.profile'))

    transfers = Transfer.query.filter_by(user_id=current_user.id).all()
    invoices = Invoice.query.filter_by(user_id=current_user.id).all()
    return render_template('profile.html', user=current_user, form=form, transfers=transfers, invoices=invoices)


@auth.route('/favorite/<path:link>')
@login_required
def toggle_favorite(link):
    """Toggle a navigation link as favourite for the current user."""
    current_user.toggle_favorite(link)
    db.session.commit()
    return redirect(request.referrer or url_for('main.home'))


@admin.route('/user_profile/<int:user_id>', methods=['GET', 'POST'])
@login_required
def user_profile(user_id):
    """View or update another user's profile."""
    if not current_user.is_admin:
        abort(403)

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    form = SetPasswordForm()
    if form.validate_on_submit():
        user.password = generate_password_hash(form.new_password.data)
        db.session.commit()
        flash('Password updated.', 'success')
        return redirect(url_for('admin.user_profile', user_id=user_id))

    transfers = Transfer.query.filter_by(user_id=user.id).all()
    invoices = Invoice.query.filter_by(user_id=user.id).all()
    return render_template('profile.html', user=user, form=form, transfers=transfers, invoices=invoices)


@admin.route('/activate_user/<int:user_id>', methods=['GET'])
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
    log_activity(f'Activated user {user_id}')
    flash('User account activated.', 'success')
    return redirect(url_for('admin.users'))  # Redirect to the user control panel


@admin.route('/controlpanel/users', methods=['GET', 'POST'])
@login_required
def users():
    """Admin interface for managing users."""
    if not current_user.is_admin:
        return abort(403)  # Only allow admins to access this page

    users = User.query.all()  # Fetch all users from the database

    if request.method == 'POST':
        user_id = request.args.get('user_id')
        action = request.form.get('action')

        user = User.query.filter_by(id=user_id).first()
        if user:
            if action == 'toggle_active':
                user.active = not user.active
                log_activity(f'Toggled active for user {user_id}')
            elif action == 'toggle_admin':
                user.is_admin = not user.is_admin
                log_activity(f'Toggled admin for user {user_id}')
            db.session.commit()
            flash('User updated successfully', 'success')
        else:
            flash('User not found', 'danger')

        return redirect(url_for('admin.users'))
    form = UserForm()
    return render_template('admin/view_users.html', users=users, form=form)


@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    """Register a new user account."""
    form = SignupForm()
    if form.validate_on_submit():
        if form.password.data != form.confirm_password.data:
            flash('Passwords must match.', 'danger')
            return redirect(url_for('auth.signup'))
        # Check if email already exists
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email already in use.', 'danger')
            return redirect(url_for('auth.signup'))

        # Create a new user instance
        new_user = User(
            email=form.email.data,
            password=generate_password_hash(form.password.data),
            active=False,
            is_admin=False
        )
        db.session.add(new_user)
        db.session.commit()
        log_activity('Signed up', new_user.id)
        flash('Account created successfully! Please wait for account activation.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/signup.html', form=form)


@admin.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    """Remove a user from the system."""
    if not current_user.is_admin:
        abort(403)  # Abort if the current user is not an admin

    user_to_delete = db.session.get(User, user_id)
    if user_to_delete is None:
        abort(404)
    db.session.delete(user_to_delete)
    db.session.commit()
    log_activity(f'Deleted user {user_id}')
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.users'))


@admin.route('/controlpanel/backups', methods=['GET'])
@login_required
def backups():
    """List available database backups."""
    if not current_user.is_admin:
        abort(403)
    from flask import current_app
    backups_dir = current_app.config['BACKUP_FOLDER']
    os.makedirs(backups_dir, exist_ok=True)
    files = sorted(os.listdir(backups_dir))
    create_form = CreateBackupForm()
    restore_form = RestoreBackupForm()
    return render_template('admin/backups.html', backups=files,
                           create_form=create_form, restore_form=restore_form)


@admin.route('/controlpanel/backups/create', methods=['POST'])
@login_required
def create_backup_route():
    """Create a new database backup."""
    if not current_user.is_admin:
        abort(403)
    form = CreateBackupForm()
    if form.validate_on_submit():
        filename = create_backup()
        log_activity(f'Created backup {filename}')
        flash('Backup created: ' + filename, 'success')
    return redirect(url_for('admin.backups'))


@admin.route('/controlpanel/backups/restore', methods=['POST'])
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
        backups_dir = current_app.config['BACKUP_FOLDER']
        os.makedirs(backups_dir, exist_ok=True)
        filepath = os.path.join(backups_dir, filename)
        file.save(filepath)
        restore_backup(filepath)
        log_activity(f'Restored backup {filename}')
        flash('Backup restored from ' + filename, 'success')
    return redirect(url_for('admin.backups'))


@admin.route('/controlpanel/backups/download/<path:filename>', methods=['GET'])
@login_required
def download_backup(filename):
    """Download a backup file."""
    if not current_user.is_admin:
        abort(403)
    from flask import current_app, send_from_directory
    backups_dir = current_app.config['BACKUP_FOLDER']
    log_activity(f'Downloaded backup {filename}')
    return send_from_directory(backups_dir, filename, as_attachment=True)


@admin.route('/controlpanel/activity', methods=['GET'])
@login_required
def activity_logs():
    """Display a log of user actions."""
    if not current_user.is_admin:
        abort(403)
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template('admin/activity_logs.html', logs=logs)




@admin.route('/controlpanel/imports', methods=['GET'])
@login_required
def import_page():
    """Display import options."""
    if not current_user.is_admin:
        abort(403)
    forms = {key: ImportForm(prefix=key) for key in IMPORT_FILES}
    labels = {
        'locations': 'Import Locations',
        'products': 'Import Products',
        'gl_codes': 'Import GL Codes',
        'items': 'Import Items',
        'customers': 'Import Customers',
        'vendors': 'Import Vendors',
        'users': 'Import Users',
    }
    return render_template('admin/imports.html', forms=forms, labels=labels)


@admin.route('/controlpanel/import/<string:data_type>', methods=['POST'])
@login_required
def import_data(data_type):
    """Import a specific data type from example files."""
    from flask import current_app
    if not current_user.is_admin:
        abort(403)
    form = ImportForm()
    if not form.validate_on_submit() or data_type not in IMPORT_FILES:
        abort(400)
    # Look for the example files inside the import_files directory which
    # lives alongside the application package. Using current_app.root_path
    # ensures the path works even when the working directory changes (e.g. in
    # the test suite).
    path = os.path.join(current_app.root_path, '..', 'import_files',
                       IMPORT_FILES[data_type])
    if data_type == 'locations':
        try:
            count = _import_locations(path)
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('admin.import_page'))
    elif data_type == 'products':
        try:
            count = _import_products(path)
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('admin.import_page'))
    elif data_type == 'gl_codes':
        count = _import_csv(path, GLCode, {'code': 'code', 'description': 'description'})
    elif data_type == 'items':
        count = _import_items(path)
    elif data_type == 'customers':
        count = _import_csv(path, Customer, {
            'first_name': 'first_name',
            'last_name': 'last_name',
        })
    elif data_type == 'vendors':
        count = _import_csv(path, Vendor, {
            'first_name': 'first_name',
            'last_name': 'last_name',
        })
    elif data_type == 'users':
        count = _import_csv(path, User, {'email': 'email', 'password': 'password'})
    else:
        abort(400)
    flash(f'Imported {count} {data_type.replace("_", " ")}.', 'success')
    return redirect(url_for('admin.import_page'))
