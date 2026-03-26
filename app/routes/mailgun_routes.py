"""Webhook routes for Mailgun inbound email processing."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from email.utils import parseaddr
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app.models import PosSalesImport, db
from app.services.pos_sales_ingest import stage_pos_sales_import
from app.utils.activity import log_activity

mailgun = Blueprint("mailgun", __name__, url_prefix="/webhooks/mailgun")


def _csv_config_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {entry.strip().lower() for entry in value.split(",") if entry.strip()}


def _extract_domain(email_value: str | None) -> str:
    if not email_value:
        return ""
    _, parsed = parseaddr(email_value)
    candidate = parsed or email_value
    if "@" not in candidate:
        return ""
    return candidate.split("@", 1)[1].strip().lower()


def _mailgun_signature_valid() -> bool:
    signing_key = current_app.config.get("MAILGUN_WEBHOOK_SIGNING_KEY") or ""
    if not signing_key:
        return False

    timestamp = (request.form.get("timestamp") or "").strip()
    token = (request.form.get("token") or "").strip()
    signature = (request.form.get("signature") or "").strip().lower()
    if not timestamp or not token or not signature:
        return False

    try:
        request_ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    max_age = int(current_app.config.get("MAILGUN_WEBHOOK_MAX_AGE_SECONDS", 15 * 60))
    now_ts = int(time.time())
    if abs(now_ts - request_ts) > max_age:
        return False

    digest = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(digest, signature)


def _message_id() -> str:
    candidates = (
        request.form.get("Message-Id"),
        request.form.get("message-id"),
        request.form.get("Message-ID"),
    )
    for value in candidates:
        if value and value.strip():
            return value.strip()
    return f"mailgun:{request.form.get('timestamp', '')}:{request.form.get('token', '')}"


@mailgun.route("/inbound", methods=["POST"])
def inbound_mailgun():
    """Receive and stage inbound Mailgun spreadsheet attachments."""

    if not _mailgun_signature_valid():
        return jsonify({"ok": False, "error": "invalid_signature"}), 401

    sender = request.form.get("sender") or request.form.get("from") or ""
    sender_value = sender.strip().lower()
    sender_domain = _extract_domain(sender_value)

    allowed_senders = _csv_config_set(current_app.config.get("MAILGUN_ALLOWED_SENDERS"))
    allowed_domains = _csv_config_set(current_app.config.get("MAILGUN_ALLOWED_SENDER_DOMAINS"))

    if allowed_senders and sender_value not in allowed_senders:
        return jsonify({"ok": False, "error": "sender_not_allowed"}), 403

    if allowed_domains and sender_domain not in allowed_domains:
        return jsonify({"ok": False, "error": "sender_domain_not_allowed"}), 403

    allowed_extensions = _csv_config_set(
        current_app.config.get("MAILGUN_ALLOWED_ATTACHMENT_EXTENSIONS", "xls,xlsx")
    )
    normalized_extensions = {
        ext if ext.startswith(".") else f".{ext}" for ext in allowed_extensions
    }

    if not request.files:
        return jsonify({"ok": False, "error": "missing_attachment"}), 400

    storage_dir_config = current_app.config.get("MAILGUN_INBOUND_STORAGE_DIR")
    storage_dir = Path(
        storage_dir_config
        or os.path.join(current_app.config["UPLOAD_FOLDER"], "mailgun_inbound")
    )
    storage_dir.mkdir(parents=True, exist_ok=True)

    imported = []
    for upload in request.files.values():
        filename = secure_filename(upload.filename or "")
        if not filename:
            continue

        extension = os.path.splitext(filename)[1].lower()
        if extension not in normalized_extensions:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "unsupported_attachment_type",
                    }
                ),
                400,
            )

        raw_bytes = upload.read()
        if not raw_bytes:
            continue

        attachment_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        persisted_filename = f"{attachment_sha256}{extension}"
        file_path = storage_dir / persisted_filename
        if not file_path.exists():
            file_path.write_bytes(raw_bytes)

        message_id = _message_id()
        sales_import = PosSalesImport(
            source_provider="mailgun",
            message_id=message_id,
            attachment_filename=filename,
            attachment_sha256=attachment_sha256,
            attachment_storage_path=str(file_path),
            status="pending",
        )
        db.session.add(sales_import)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            existing = PosSalesImport.query.filter_by(
                source_provider="mailgun",
                message_id=message_id,
                attachment_sha256=attachment_sha256,
            ).first()
            if existing:
                imported.append({"id": existing.id, "duplicate": True})
                log_activity(
                    f"Received duplicate POS sales import webhook payload for existing import {existing.id}"
                )
                continue
            return jsonify({"ok": False, "error": "duplicate_import"}), 409

        try:
            stage_pos_sales_import(sales_import, str(file_path), extension)
            db.session.commit()
            imported.append({"id": sales_import.id, "duplicate": False})
            log_activity(f"Received POS sales import {sales_import.id} via Mailgun webhook")
        except Exception:
            db.session.rollback()
            failure = PosSalesImport(
                source_provider="mailgun",
                message_id=f"{message_id}:failed:{secrets.token_hex(4)}",
                attachment_filename=filename,
                attachment_sha256=attachment_sha256,
                attachment_storage_path=str(file_path),
                status="failed",
                failure_reason="Unable to parse POS spreadsheet attachment.",
            )
            db.session.add(failure)
            db.session.commit()
            current_app.logger.exception("Failed to stage inbound Mailgun attachment")
            log_activity(
                f"Failed to parse POS sales import attachment via Mailgun webhook; failure import {failure.id}"
            )
            return jsonify({"ok": False, "error": "parse_failed"}), 422

    if not imported:
        return jsonify({"ok": False, "error": "missing_attachment"}), 400

    return jsonify({"ok": True, "imports": imported}), 202
