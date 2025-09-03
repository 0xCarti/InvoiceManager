def login(client, email: str, password: str):
    """Helper to login a user in tests."""
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )
