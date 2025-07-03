import os
from werkzeug.security import generate_password_hash
from app import db
from app.models import User, Setting
from tests.utils import login


def test_admin_can_update_gst_number(client, app):
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    admin_pass = os.getenv('ADMIN_PASS', 'adminpass')
    with app.app_context():
        # ensure default setting exists
        setting = Setting.query.filter_by(name='GST').first()
        assert setting is not None
        setting.value = ''
        db.session.commit()
    with client:
        login(client, admin_email, admin_pass)
        resp = client.post('/controlpanel/settings', data={'gst_number': '987654321'}, follow_redirects=True)
        assert resp.status_code == 200
    with app.app_context():
        setting = Setting.query.filter_by(name='GST').first()
        assert setting.value == '987654321'
        from app import GST
        assert GST == '987654321'
