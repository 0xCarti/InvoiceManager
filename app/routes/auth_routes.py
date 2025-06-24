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
)

from app.models import User, db, Transfer, Invoice, ActivityLog
from app.activity_logger import log_activity
from app.backup_utils import create_backup, restore_backup

auth = Blueprint('auth', __name__)
admin = Blueprint('admin', __name__)


@auth.route('/login', methods=['GET', 'POST'])
def login():
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
    user_id = current_user.id
    logout_user()
    log_activity('Logged out', user_id)
    return redirect(url_for('auth.login'))


@auth.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
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


@admin.route('/user_profile/<int:user_id>', methods=['GET', 'POST'])
@login_required
def user_profile(user_id):
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
    if not current_user.is_admin:
        abort(403)
    from flask import current_app, send_from_directory
    backups_dir = current_app.config['BACKUP_FOLDER']
    log_activity(f'Downloaded backup {filename}')
    return send_from_directory(backups_dir, filename, as_attachment=True)


@admin.route('/controlpanel/activity', methods=['GET'])
@login_required
def activity_logs():
    if not current_user.is_admin:
        abort(403)
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template('admin/activity_logs.html', logs=logs)
