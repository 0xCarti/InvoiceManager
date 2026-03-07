from werkzeug.security import generate_password_hash

from app.models import User
from tests.utils import extract_csrf_token, login


_PURCHASE_UPLOAD_SESSION_KEY = "purchase_order_upload"


def test_continue_import_blocked_when_duplicate_blockers_remain(client, app):
    with app.app_context():
        user = User(
            email="blockers@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        from app import db

        db.session.add(user)
        db.session.commit()

    with client:
        login(client, "blockers@example.com", "pass")
        with client.session_transaction() as session_data:
            session_data[_PURCHASE_UPLOAD_SESSION_KEY] = {
                "vendor_id": 1,
                "items": [{"item_id": 123, "quantity": 1}],
                "duplicate_blockers": [
                    {
                        "id": "b1",
                        "category": "producer_address",
                        "row_label": "Row 1",
                    }
                ],
            }

        response = client.get("/purchase_orders/create", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/purchase_orders/resolve_vendor_items")


def test_duplicate_blocker_decision_persists_before_continue(client, app):
    with app.app_context():
        user = User(
            email="resolve-blockers@example.com",
            password=generate_password_hash("pass"),
            active=True,
        )
        from app import db

        db.session.add(user)
        db.session.commit()

    with client:
        login(client, "resolve-blockers@example.com", "pass")
        with client.session_transaction() as session_data:
            session_data[_PURCHASE_UPLOAD_SESSION_KEY] = {
                "vendor_id": 1,
                "items": [{"item_id": 456, "quantity": 1}],
                "duplicate_blockers": [
                    {
                        "id": "b2",
                        "category": "duplicate_persistence",
                        "row_label": "Row 2",
                        "supports_merge": True,
                    }
                ],
            }

        page = client.get("/purchase_orders/resolve_vendor_items")
        csrf_token = extract_csrf_token(page, required=False)

        form_data = {
            "step": "resolve_duplicate_blocker",
            "blocker_id": "b2",
            "blocker_action": "skip_row",
        }
        if csrf_token:
            form_data["csrf_token"] = csrf_token

        post_response = client.post(
            "/purchase_orders/resolve_vendor_items",
            data=form_data,
            follow_redirects=True,
        )
        assert post_response.status_code == 200
        assert b"Blocked row skipped for this import." in post_response.data

        with client.session_transaction() as session_data:
            persisted = session_data.get(_PURCHASE_UPLOAD_SESSION_KEY) or {}
            assert persisted.get("duplicate_blockers") == []

        continue_response = client.get("/purchase_orders/create", follow_redirects=False)
        assert continue_response.status_code == 200
