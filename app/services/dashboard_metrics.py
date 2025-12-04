"""Helper functions for collecting dashboard metrics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from app import db
from app.models import Event, Invoice, PurchaseInvoice, PurchaseOrder, Transfer
from app.services.event_service import current_user_today, event_schedule


def _coalesce_scalar(query) -> float:
    """Return a numeric scalar result or ``0.0`` when ``None``."""

    result = query.scalar()
    return float(result or 0.0)


def transfer_summary() -> Dict[str, int]:
    """Return counts for transfers used on the dashboard."""

    total = _coalesce_scalar(db.session.query(func.count(Transfer.id)))
    completed = _coalesce_scalar(
        db.session.query(func.count(Transfer.id)).filter(Transfer.completed.is_(True))
    )
    pending = int(total - completed)

    return {
        "total": int(total),
        "completed": int(completed),
        "pending": pending,
    }


def purchase_order_summary(today: Optional[date] = None) -> Dict[str, Any]:
    """Return open counts and totals for purchase orders."""

    today = today or date.today()
    open_orders = PurchaseOrder.query.filter(PurchaseOrder.received.is_(False))
    overdue_orders = open_orders.filter(PurchaseOrder.expected_date < today)

    return {
        "open_count": open_orders.count(),
        "overdue_count": overdue_orders.count(),
        "expected_total": _coalesce_scalar(
            db.session.query(func.sum(PurchaseOrder.expected_total_cost)).filter(
                PurchaseOrder.received.is_(False)
            )
        ),
    }


def purchase_invoice_summary() -> Dict[str, Any]:
    """Return totals for received purchase invoices."""

    invoices = PurchaseInvoice.query.all()
    total = sum(invoice.total for invoice in invoices)

    return {
        "count": len(invoices),
        "total": float(total),
    }


def invoices_pending_posting(limit: int = 5) -> Dict[str, Any]:
    """Return recently received purchase invoices that need posting/payment."""

    query = PurchaseInvoice.query.order_by(PurchaseInvoice.received_date.desc())
    total = query.count()

    return {
        "items": query.limit(limit).all(),
        "total": total,
    }


def invoice_summary() -> Dict[str, Any]:
    """Return counts and totals for customer invoices."""

    invoices = Invoice.query.all()
    total = sum(invoice.total for invoice in invoices)

    return {
        "count": len(invoices),
        "total": float(total),
    }


def pending_purchase_orders(limit: int = 5) -> Dict[str, Any]:
    """Return open purchase orders awaiting receipt."""

    query = PurchaseOrder.query.filter(PurchaseOrder.received.is_(False)).order_by(
        PurchaseOrder.expected_date.asc(), PurchaseOrder.order_date.asc()
    )
    total = query.count()

    return {
        "items": query.limit(limit).all(),
        "total": total,
    }


def pending_transfers(limit: int = 5) -> Dict[str, Any]:
    """Return transfers that still need approval/completion."""

    query = Transfer.query.filter(Transfer.completed.is_(False)).order_by(
        Transfer.date_created.desc()
    )
    total = query.count()

    return {
        "items": query.limit(limit).all(),
        "total": total,
    }


def event_summary(today: Optional[date] = None) -> Dict[str, Any]:
    """Return today's and upcoming event counts for dashboard widgets."""

    today = current_user_today(today)
    next_day = today + timedelta(days=1)

    todays_events = Event.query.filter(
        Event.closed.is_(False),
        Event.start_date <= today,
        Event.end_date >= today,
    )
    upcoming_events = Event.query.filter(
        Event.closed.is_(False),
        Event.start_date > today,
    )
    next_event = upcoming_events.order_by(Event.start_date.asc()).first()
    next_day_events = (
        Event.query.filter(
            Event.closed.is_(False),
            Event.start_date == next_day,
        )
        .order_by(Event.start_date.asc(), Event.name.asc())
        .all()
    )

    return {
        "today_count": todays_events.count(),
        "upcoming_count": upcoming_events.count(),
        "next_event": next_event,
        "next_day": next_day,
        "next_day_events": next_day_events,
    }


def dashboard_context() -> Dict[str, Any]:
    """Aggregate metrics for the dashboard view."""

    today = current_user_today()

    events = event_summary(today)
    events["schedule"] = event_schedule(today)

    weekly_activity = weekly_transfer_purchase_activity(today=today)

    return {
        "transfers": transfer_summary(),
        "purchase_orders": purchase_order_summary(today),
        "purchase_invoices": purchase_invoice_summary(),
        "invoices": invoice_summary(),
        "events": events,
        "charts": {
            "weekly_activity": weekly_activity,
        },
        "queues": {
            "purchase_orders": pending_purchase_orders(),
            "transfers": pending_transfers(),
            "purchase_invoices": invoices_pending_posting(),
        },
    }


def weekly_transfer_purchase_activity(
    weeks: int = 6, today: Optional[date] = None
) -> List[Dict[str, Any]]:
    """Return weekly counts/totals for transfers, purchases, and sales."""

    today = today or date.today()

    def start_of_week(value: date) -> date:
        return value - timedelta(days=value.weekday())

    start_week = start_of_week(today) - timedelta(weeks=weeks - 1)
    week_starts = [start_week + timedelta(weeks=i) for i in range(weeks)]
    buckets = {
        start: {
            "week_start": start.isoformat(),
            "week_end": (start + timedelta(days=6)).isoformat(),
            "label": f"{start.strftime('%b %d')} – {(start + timedelta(days=6)).strftime('%b %d')}",
            "transfers": 0,
            "purchases": 0,
            "purchase_total": 0.0,
            "sales": 0,
            "sales_total": 0.0,
        }
        for start in week_starts
    }

    transfer_start_dt = datetime.combine(start_week, datetime.min.time())
    transfers = Transfer.query.filter(Transfer.date_created >= transfer_start_dt).all()

    for transfer in transfers:
        bucket_start = start_of_week(transfer.date_created.date())
        if bucket_start in buckets:
            buckets[bucket_start]["transfers"] += 1

    purchases = PurchaseInvoice.query.filter(
        PurchaseInvoice.received_date >= start_week
    ).all()

    for invoice in purchases:
        bucket_start = start_of_week(invoice.received_date)
        if bucket_start in buckets:
            buckets[bucket_start]["purchases"] += 1
            buckets[bucket_start]["purchase_total"] += float(invoice.total)

    sales = Invoice.query.filter(Invoice.date_created >= transfer_start_dt).all()

    for sale in sales:
        bucket_start = start_of_week(sale.date_created.date())
        if bucket_start in buckets:
            buckets[bucket_start]["sales"] += 1
            buckets[bucket_start]["sales_total"] += float(sale.total)

    return [buckets[start] for start in sorted(buckets.keys())]
