from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def email_settings(config: dict) -> dict:
    email = dict(config.get("email", {}))
    email["password"] = os.getenv("SMTP_PASSWORD", "")
    return email


def can_send(config: dict) -> tuple[bool, str]:
    email = email_settings(config)
    if not email.get("enabled"):
        return False, "Email is disabled. Set SMTP_HOST and EMAIL_TO, or email.enabled in config.json."
    if not email.get("smtp_host") or not email.get("to"):
        return False, "Email is not configured. Set SMTP_HOST and EMAIL_TO."
    if email.get("smtp_user") and not email.get("password"):
        recipient = email.get("to")
        return (
            False,
            "SMTP_PASSWORD is missing from .env. Create a Gmail app password at "
            "https://myaccount.google.com/apppasswords and save it as SMTP_PASSWORD "
            f"so the daily report can be sent to {recipient}.",
        )
    host = str(email.get("smtp_host") or "")
    if "gmail.com" in host and email.get("smtp_user"):
        compact = (email.get("password") or "").replace(" ", "")
        if not (len(compact) == 16 and compact.isalpha()):
            return (
                False,
                "Gmail rejected SMTP_PASSWORD. An app password is 16 letters and has no numbers or symbols. "
                "Create one at https://myaccount.google.com/apppasswords, replace SMTP_PASSWORD in .env, and save the file.",
            )
    return True, "ready"


def send_report(config: dict, subject: str, text_body: str, html_body: str) -> tuple[bool, str]:
    ready, reason = can_send(config)
    if not ready:
        return False, reason
    email = email_settings(config)
    sender = email.get("smtp_from") or email.get("smtp_user") or email.get("to")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = email["to"]
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    host = email["smtp_host"]
    port = int(email.get("smtp_port") or 587)
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if email.get("use_tls", True):
                smtp.starttls()
            user = email.get("smtp_user") or ""
            if user:
                password = email.get("password") or ""
                if "gmail.com" in str(host):
                    password = password.replace(" ", "")
                smtp.login(user, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        return (
            False,
            "Gmail rejected the login. Create a new app password at "
            "https://myaccount.google.com/apppasswords, replace SMTP_PASSWORD in .env, and save the file.",
        )
    except (OSError, smtplib.SMTPException) as exc:
        if isinstance(exc, smtplib.SMTPServerDisconnected) or "unexpectedly closed" in str(exc).lower():
            return (
                False,
                "Gmail closed the connection during login. The app password was not accepted. "
                "Create a new one at https://myaccount.google.com/apppasswords and replace SMTP_PASSWORD in .env.",
            )
        return False, f"Email delivery failed: {exc}"
    return True, f"Email sent to {email['to']}"
