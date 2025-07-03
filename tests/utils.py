from typing import Optional


def signup(client, email: str, password: str, confirm_password: Optional[str] = None):
    """Helper to sign up a user in tests."""
    if confirm_password is None:
        confirm_password = password
    return client.post(
        '/auth/signup',
        data={
            'email': email,
            'password': password,
            'confirm_password': confirm_password,
        },
        follow_redirects=True,
    )


def login(client, email: str, password: str):
    """Helper to login a user in tests."""
    return client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )
