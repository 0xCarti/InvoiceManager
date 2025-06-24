from flask_login import current_user
from app.models import ActivityLog, db


def log_activity(activity, user_id=None):
    if user_id is None:
        if current_user and not current_user.is_anonymous:
            user_id = current_user.id
    log = ActivityLog(user_id=user_id, activity=activity)
    db.session.add(log)
    db.session.commit()
