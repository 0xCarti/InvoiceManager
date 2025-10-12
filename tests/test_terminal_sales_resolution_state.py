from datetime import date
from secrets import token_urlsafe

from app import db
from app.models import Event, EventLocation, Location
from app.routes.event_routes import (
    _TERMINAL_SALES_STATE_KEY,
    _terminal_sales_serializer,
)


def _create_event(app):
    with app.app_context():
        event = Event(
            name="Terminal Upload",
            start_date=date.today(),
            end_date=date.today(),
        )
        prairie = Location(name="Prairie Grill")
        keystone = Location(name="Keystone Kravings")
        db.session.add_all([event, prairie, keystone])
        db.session.flush()

        prairie_el = EventLocation(event_id=event.id, location_id=prairie.id)
        keystone_el = EventLocation(event_id=event.id, location_id=keystone.id)
        db.session.add_all([prairie_el, keystone_el])
        db.session.commit()

        return event.id


def test_stale_terminal_sales_state_is_rejected_after_reset(client, app):
    event_id = _create_event(app)

    with app.app_context():
        from app.models import User

        user = User(email="test@example.com", password="", active=True)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    with app.test_request_context():
        serializer = _terminal_sales_serializer()
        token_id = token_urlsafe(16)
        state_token = serializer.dumps(
            {
                "queue": [
                    {
                        "event_location_id": None,
                        "location_name": "Prairie Grill",
                        "sales_location": "PRAIRIE GRILL",
                        "price_issues": [],
                        "menu_issues": [],
                    }
                ],
                "pending_sales": [],
                "pending_totals": [],
                "selected_locations": [],
                "issue_index": 0,
                "token_id": token_id,
            }
        )

    with client.session_transaction() as sess:
        store = dict(sess.get(_TERMINAL_SALES_STATE_KEY, {}))
        store[str(event_id)] = token_id
        sess[_TERMINAL_SALES_STATE_KEY] = store

    # Simulate clicking "Start Over", which should clear the stored token.
    client.get(f"/events/{event_id}/sales/upload")

    with client.session_transaction() as sess:
        store_after_reset = sess.get(_TERMINAL_SALES_STATE_KEY, {})
        assert str(event_id) not in store_after_reset

    stale_post = client.post(
        f"/events/{event_id}/sales/upload",
        data={
            "step": "resolve",
            "state_token": state_token,
            "payload": "{}",
            "mapping_filename": "terminal.xls",
        },
        follow_redirects=True,
    )

    page = stale_post.get_data(as_text=True)
    assert "resolution session is no longer valid" in page
    assert "Sales File" in page
