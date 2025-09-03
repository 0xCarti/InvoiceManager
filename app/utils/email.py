import os
import smtplib
from email.message import EmailMessage


def send_email(to_address: str, subject: str, body: str):
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

    with smtplib.SMTP(host, port) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password or "")
        server.send_message(msg)
