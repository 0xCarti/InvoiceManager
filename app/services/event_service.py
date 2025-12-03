"""Helpers for retrieving event data for dashboard widgets."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List

from app.models import Event


@dataclass
class CalendarDay:
    """Representation of a single calendar day and the events on it."""

    date: date
    count: int

    @property
    def day(self) -> int:
        return self.date.day


def _event_status(event: Event, today: date) -> str:
    """Return a label describing the event's status relative to ``today``."""

    if event.end_date < today:
        return "past_due"
    if event.start_date > today:
        return "upcoming"
    return "active"


def _calendar_days(events: Iterable[Event], today: date) -> List[CalendarDay]:
    """Return calendar day data for the month that contains ``today``."""

    month_start = date(today.year, today.month, 1)
    _, days_in_month = monthrange(today.year, today.month)

    calendar_days: List[CalendarDay] = []
    for offset in range(days_in_month):
        current_day = month_start + timedelta(days=offset)
        count = sum(
            1
            for event in events
            if event.start_date <= current_day <= event.end_date
        )
        calendar_days.append(CalendarDay(date=current_day, count=count))

    return calendar_days


def event_schedule(today: date | None = None) -> dict:
    """Return upcoming/active events and calendar data for the dashboard."""

    today = today or date.today()

    open_events = (
        Event.query.filter(Event.closed.is_(False))
        .order_by(Event.start_date.asc(), Event.end_date.asc())
        .all()
    )

    calendar_days = _calendar_days(open_events, today)

    return {
        "events": [
            {
                "id": event.id,
                "name": event.name,
                "start_date": event.start_date,
                "end_date": event.end_date,
                "status": _event_status(event, today),
            }
            for event in open_events
        ],
        "calendar": {
            "month_label": today.strftime("%B %Y"),
            "days": calendar_days,
            "today": today,
        },
    }
