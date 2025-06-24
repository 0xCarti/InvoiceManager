from werkzeug.security import generate_password_hash

from app import db
from app.models import User, Location


def signup(client, email, password):
    return client.post(
        '/auth/signup',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )


def login(client, email, password):
    return client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )


def test_signup_creates_user(client, app):
    response = signup(client, 'new@example.com', 'secret')
    assert response.status_code == 200
    assert b'Account created successfully' in response.data

    with app.app_context():
        user = User.query.filter_by(email='new@example.com').first()
        assert user is not None
        assert not user.active
        assert not user.is_admin


def test_login_inactive_user(client, app):
    with app.app_context():
        user = User(
            email='inactive@example.com',
            password=generate_password_hash('password'),
            active=False,
        )
        db.session.add(user)
        db.session.commit()

    response = login(client, 'inactive@example.com', 'password')
    assert response.status_code == 200
    assert b'Please contact system admin to activate account.' in response.data


def test_add_location(client, app):
    with app.app_context():
        user = User(
            email='loc@example.com',
            password=generate_password_hash('pass'),
            active=True,
        )
        db.session.add(user)
        db.session.commit()

    # Login and add location within the same client context
    with client:
        login(client, 'loc@example.com', 'pass')
        response = client.post('/locations/add', data={'name': 'Warehouse'}, follow_redirects=True)
        assert response.status_code == 200

    with app.app_context():
        location = Location.query.filter_by(name='Warehouse').first()
        assert location is not None

