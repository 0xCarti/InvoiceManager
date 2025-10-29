import os
import smtplib
from email.message import EmailMessage
from typing import Optional, Sequence, Tuple


Attachment = Tuple[str, bytes, str]


def send_email(
    to_address: str,
    subject: str,
    body: str,
    attachments: Optional[Sequence[Attachment]] = None,
):
    """Send an email using SMTP settings from environment variables."""
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "25"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    from_address = os.getenv("SMTP_SENDER", username)
    use_tls = os.getenv("SMTP_USE_TLS", "false").lower() in (
        "1",
        "true",
        "yes",
    )

    if not host or not from_address:
        raise RuntimeError("SMTP settings not configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    msg.set_content(body)

    if attachments:
        for filename, content, mimetype in attachments:
            maintype, _, subtype = mimetype.partition("/")
            if not subtype:
                maintype, subtype = "application", "octet-stream"
            if isinstance(content, str):
                content = content.encode("utf-8")
            msg.add_attachment(
                content,
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

    with smtplib.SMTP(host, port) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password or "")
        server.send_message(msg)
