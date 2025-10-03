import os

from werkzeug.security import generate_password_hash

from app import db
from app.models import Setting, User
from app.utils.backup import UNIT_SECONDS
from app.utils.units import parse_conversion_setting
from tests.utils import login


def test_admin_can_update_settings(client, app):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "adminpass")
    with app.app_context():
        # ensure default setting exists
        setting = Setting.query.filter_by(name="GST").first()
        assert setting is not None
        setting.value = ""
        db.session.commit()
    with client:
        login(client, admin_email, admin_pass)
        resp = client.post(
            "/controlpanel/settings",
            data={
                "gst_number": "987654321",
                "default_timezone": "US/Eastern",
                "auto_backup_enabled": "y",
                "auto_backup_interval_value": "2",
                "auto_backup_interval_unit": "week",
                "max_backups": "5",
                "convert_ounce": "gram",
                "convert_gram": "ounce",
                "convert_each": "each",
                "convert_millilitre": "ounce",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
    with app.app_context():
        setting = Setting.query.filter_by(name="GST").first()
        assert setting.value == "987654321"
        from app import GST

        assert GST == "987654321"
        tz_setting = Setting.query.filter_by(name="DEFAULT_TIMEZONE").first()
        assert tz_setting.value == "US/Eastern"
        from app import DEFAULT_TIMEZONE

        assert DEFAULT_TIMEZONE == "US/Eastern"
        auto_setting = Setting.query.filter_by(
            name="AUTO_BACKUP_ENABLED"
        ).first()
        assert auto_setting.value == "1"
        interval_value = Setting.query.filter_by(
            name="AUTO_BACKUP_INTERVAL_VALUE"
        ).first()
        assert interval_value.value == "2"
        interval_unit = Setting.query.filter_by(
            name="AUTO_BACKUP_INTERVAL_UNIT"
        ).first()
        assert interval_unit.value == "week"
        max_setting = Setting.query.filter_by(name="MAX_BACKUPS").first()
        assert max_setting.value == "5"
        conversion_setting = Setting.query.filter_by(
            name="BASE_UNIT_CONVERSIONS"
        ).first()
        mapping = parse_conversion_setting(conversion_setting.value)
        assert mapping == {
            "ounce": "gram",
            "gram": "ounce",
            "each": "each",
            "millilitre": "ounce",
        }
        assert app.config["AUTO_BACKUP_ENABLED"] is True
        assert app.config["AUTO_BACKUP_INTERVAL_VALUE"] == 2
        assert app.config["AUTO_BACKUP_INTERVAL_UNIT"] == "week"
        assert app.config["AUTO_BACKUP_INTERVAL"] == 2 * UNIT_SECONDS["week"]
        assert app.config["MAX_BACKUPS"] == 5
        assert app.config["BASE_UNIT_CONVERSIONS"] == mapping
