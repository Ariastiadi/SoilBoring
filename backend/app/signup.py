"""Account requests from the sign-in page ("Create an account").

Anyone can ask for an account; nobody gets in until an administrator approves the request
and chooses the role. The applicant picks the password at request time; it is stored only
as a hash and moves into users.json on approval.

Safeguards:
* the answer to a request is the same whether or not the email already has an account or a
  request, so the form cannot be used to find out who has an account;
* at most SIGNUPS_PER_HOUR requests per client address per hour, at most MAX_PENDING open
  requests, and requests not handled within PENDING_DAYS are dropped;
* switched off with SELF_SIGNUP=false, or by an admin in Company settings.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from . import docstore
from .auth import MIN_PASSWORD_LENGTH, create_user_with_hash, hash_new_password, user_exists
from .models import normalize_email

REQUESTS_DOC = "signup_requests.json"
MAX_PENDING = 100
PENDING_DAYS = 30
SIGNUPS_PER_HOUR = 5

# What the applicant says they do, and the role it suggests to the admin.
DEPARTMENTS: Dict[str, str] = {
    "field": "general",
    "lab": "lab",
    "engineering": "manager",
    "finance": "finance",
    "management": "manager",
    "other": "general",
}


def enabled() -> bool:
    """Self sign-up is on unless SELF_SIGNUP=false or an admin switched it off in Company settings."""
    if os.environ.get("SELF_SIGNUP", "true").strip().lower() in {"0", "false", "no", "off"}:
        return False
    from . import records

    try:
        settings = records.get_singleton("settings")
    except Exception:  # settings unreadable: fall back to the default
        settings = None
    return (settings or {}).get("self_signup") is not False


def _load() -> Dict[str, Dict[str, Any]]:
    text = docstore.read_text(REQUESTS_DOC)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, list):
        return {}
    cutoff = time.time() - PENDING_DAYS * 86400
    out: Dict[str, Dict[str, Any]] = {}
    for entry in data:
        if isinstance(entry, dict) and isinstance(entry.get("email"), str) and float(entry.get("at") or 0) > cutoff:
            out[entry["email"].lower()] = entry
    return out


def _save(requests: Dict[str, Dict[str, Any]]) -> None:
    items = sorted(requests.values(), key=lambda r: r.get("at") or 0)
    docstore.write_text(REQUESTS_DOC, json.dumps(items, indent=2) + "\n", private=True)


def submit(email: str, password: str, name: str, department: str, note: str, source: str) -> bool:
    """Store a request; True when a new one was stored. Raises only for problems the applicant can fix (or the limits)."""
    from .auth import allow_signup

    if not enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account requests are switched off; ask an administrator for an account")
    try:
        email = normalize_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    name = " ".join((name or "").split())
    if len(name) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter your full name")
    if department not in DEPARTMENTS:
        department = "other"
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    # Counted before the (slow) password hash, so the form cannot be used to load the server.
    if not allow_signup(source, SIGNUPS_PER_HOUR):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many account requests from this connection. Try again in an hour.",
            headers={"Retry-After": "3600"},
        )
    password_hash = hash_new_password(password)
    if user_exists(email):
        return False  # same answer as a new request: the form does not reveal existing accounts
    with docstore.lock(REQUESTS_DOC):
        requests = _load()
        if email.lower() in requests:
            return False  # the first request stands; it cannot be overwritten by someone else
        if len(requests) >= MAX_PENDING:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Too many account requests are waiting. Ask an administrator for an account.",
            )
        requests[email.lower()] = {
            "email": email,
            "name": name[:120],
            "department": department,
            "note": " ".join((note or "").split())[:300],
            "password": password_hash,
            "at": time.time(),
        }
        _save(requests)
    return True


def pending() -> List[Dict[str, Any]]:
    """Open requests for the admin, oldest first, without the password hash."""
    return [
        {
            "email": r["email"],
            "name": r.get("name") or "",
            "department": r.get("department") or "other",
            "suggested_role": DEPARTMENTS.get(r.get("department") or "other", "general"),
            "note": r.get("note") or "",
            "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(r.get("at") or 0))),
        }
        for r in sorted(_load().values(), key=lambda r: r.get("at") or 0)
    ]


def _take(email: str) -> Optional[Dict[str, Any]]:
    with docstore.lock(REQUESTS_DOC):
        requests = _load()
        found = requests.pop((email or "").strip().lower(), None)
        if found is not None:
            _save(requests)
    return found


def approve(email: str, role: str) -> Dict[str, str]:
    request = _take(email)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account request not found")
    try:
        return create_user_with_hash(request["email"], request["password"], role, request.get("name") or "")
    except HTTPException:
        if user_exists(request["email"]):
            raise
        with docstore.lock(REQUESTS_DOC):  # e.g. a wrong role: keep the request for another try
            requests = _load()
            requests.setdefault(request["email"].lower(), request)
            _save(requests)
        raise


def reject(email: str) -> None:
    if _take(email) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account request not found")
