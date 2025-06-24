import os
import pytest
from flask import url_for
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import User


@pytest.fixture
def app(tmp_path):
    os.environ.setdefault('SECRET_KEY', 'testsecret')
    os.environ.setdefault('ADMIN_EMAIL', 'admin@example.com')
    os.environ.setdefault('ADMIN_PASS', 'adminpass')

    cwd = os.getcwd()
    os.chdir(tmp_path)
    app, _ = create_app(['--demo'])
    os.chdir(cwd)

    app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})

    with app.app_context():
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def test_login_redirect(client, app):
    with app.app_context():
        user = User(
            email='test@example.com',
            password=generate_password_hash('password'),
            active=True
        )
        db.session.add(user)
        db.session.commit()
        expected = url_for('transfer.view_transfers')

    response = client.post('/auth/login', data={
        'email': 'test@example.com',
        'password': 'password'
    })

    assert response.status_code == 302
    assert response.headers['Location'].endswith(expected)
