"""Small, environment-driven settings shared by several modules."""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Shown in exports (e.g. the AGS4 "data file producer"); empty = the app name.
ORG_NAME = os.environ.get("ORG_NAME", "").strip()
APP_NAME = "Soil Boring Ops"

# Field logs are dated in local time; "last 7 days" and report timestamps follow it.
_TZ_NAME = os.environ.get("APP_TIMEZONE", "Asia/Jakarta").strip() or "Asia/Jakarta"
try:
    APP_TIMEZONE = ZoneInfo(_TZ_NAME)
except (ZoneInfoNotFoundError, ValueError):
    logger.warning("Unknown APP_TIMEZONE %r; using UTC", _TZ_NAME)
    _TZ_NAME = "UTC"
    APP_TIMEZONE = ZoneInfo("UTC")


def producer_name() -> str:
    return f"{ORG_NAME} - {APP_NAME}" if ORG_NAME else APP_NAME


def local_now() -> datetime:
    """Naive local "now" (the CSV dates are naive local dates)."""
    return datetime.now(timezone.utc).astimezone(APP_TIMEZONE).replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()


def timezone_label() -> str:
    return _TZ_NAME
