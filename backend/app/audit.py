"""Activity log: who changed what, and when.

Every change to logs, depth data, photos and accounts is appended to one document
(``audit.json``, newest last). The newest ``MAX_EVENTS`` entries are kept. Passwords,
codes and photo contents are never written here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import docstore

DOC = "audit.json"
MAX_EVENTS = 5000
# Events anyone can trigger without signing in (password-reset requests) are kept apart,
# so flooding them can never push real history out of the main log.
PUBLIC_DOC = "audit_public.json"
MAX_PUBLIC_EVENTS = 500
ACCOUNT_PREFIXES = ("account.", "user.")
logger = logging.getLogger(__name__)


def is_account_event(event: Dict[str, Any]) -> bool:
    return str(event.get("action", "")).startswith(ACCOUNT_PREFIXES)


def _load(doc: str = DOC) -> List[Dict[str, Any]]:
    text = docstore.read_text(doc)
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def record(
    user: Optional[str], action: str, target: str = "", changes: Optional[Dict[str, Any]] = None, *, public: bool = False
) -> None:
    """Append one event. Never raises: a failing activity log must not block the change itself.

    ``public``: the event can be triggered without signing in (kept in a separate, smaller log).
    """
    doc, limit = (PUBLIC_DOC, MAX_PUBLIC_EVENTS) if public else (DOC, MAX_EVENTS)
    event: Dict[str, Any] = {
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "user": user or "",
        "action": action,
        "target": target,
    }
    if changes:
        event["changes"] = changes
    try:
        with docstore.lock(doc):
            events = _load(doc)
            events.append(event)
            if len(events) > limit:
                events = events[-limit:]
            docstore.write_text(doc, json.dumps(events, ensure_ascii=False, separators=(",", ":"), default=str))
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not write the activity log")


def diff(before: Dict[str, Any], after: Dict[str, Any], keys: Optional[List[str]] = None) -> Dict[str, List[Any]]:
    """{field: [old, new]} for the fields that changed."""
    out: Dict[str, List[Any]] = {}
    for key in keys or sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if (old or "") != (new or "") and old != new:
            out[key] = [old, new]
    return out


def list_events(
    target: Optional[str] = None, user: Optional[str] = None, limit: int = 200, *, logs_only: bool = False
) -> List[Dict[str, Any]]:
    """Newest first. ``logs_only`` leaves out account events (for non-admin users)."""
    events = _load(DOC) + ([] if logs_only else _load(PUBLIC_DOC))
    events.sort(key=lambda e: str(e.get("at", "")))
    if logs_only:
        events = [e for e in events if not is_account_event(e)]
    if target:
        wanted = target.strip().lower()
        events = [e for e in events if str(e.get("target", "")).lower() == wanted]
    if user:
        who = user.strip().lower()
        events = [e for e in events if str(e.get("user", "")).lower() == who]
    return list(reversed(events[-limit:]))
