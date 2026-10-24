"""Optional email (password-reset links), sent through any SMTP server.

Turned on by SMTP_HOST plus a known site address (APP_BASE_URL, or Vercel's production
domain). Free options: a Gmail/Outlook account with an app password, or a transactional
mail service's free plan. Without it, "forgot password" works with recovery codes.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


def base_url() -> Optional[str]:
    """Address used in links. Never taken from the request (Host header) to avoid link spoofing."""
    configured = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    vercel = (os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or "").strip().rstrip("/")
    return f"https://{vercel}" if vercel else None


def email_enabled() -> bool:
    return bool((os.environ.get("SMTP_HOST") or "").strip()) and base_url() is not None


def send(to: str, subject: str, body: str) -> bool:
    if not email_enabled():
        return False
    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or user or f"no-reply@{host}").strip()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    try:
        if port == 465 or (os.environ.get("SMTP_SSL") or "").lower() in {"1", "true", "yes"}:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls(context=context)
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("Could not send email to %s: %s", to, exc)
        return False
