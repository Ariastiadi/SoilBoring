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
logger = logging.getLogger(__name__)


def _load() -> List[Dict[str, Any]]:
    text = docstore.read_text(DOC)
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def record(user: Optional[str], action: str, target: str = "", changes: Optional[Dict[str, Any]] = None) -> None:
    """Append one event. Never raises: a failing activity log must not block the change itself."""
    event: Dict[str, Any] = {
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "user": user or "",
        "action": action,
        "target": target,
    }
    if changes:
        event["changes"] = changes
    try:
        with docstore.lock(DOC):
            events = _load()
            events.append(event)
            if len(events) > MAX_EVENTS:
                events = events[-MAX_EVENTS:]
            docstore.write_text(DOC, json.dumps(events, ensure_ascii=False, separators=(",", ":"), default=str))
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


def list_events(target: Optional[str] = None, user: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    events = _load()
    if target:
        wanted = target.strip().lower()
        events = [e for e in events if str(e.get("target", "")).lower() == wanted]
    if user:
        who = user.strip().lower()
        events = [e for e in events if str(e.get("user", "")).lower() == who]
    return list(reversed(events[-limit:]))
