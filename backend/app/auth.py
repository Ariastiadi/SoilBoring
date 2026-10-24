from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import normalize_email
from .storage import DATA_PATH, atomic_write_text


logger = logging.getLogger(__name__)

USER_FILE = DATA_PATH / "users.json"
SECRET_FILE = DATA_PATH / ".token_secret"
TOKEN_TTL = int(os.environ.get("AUTH_TOKEN_TTL", "28800"))  # 8 hours
VALID_ROLES = {"admin", "general"}
MIN_PASSWORD_LENGTH = 8

# Password hashing: PBKDF2-HMAC-SHA256 (stdlib, no extra dependency).
PBKDF2_ITERATIONS = 600_000
_HASH_PREFIX = "pbkdf2_sha256"
_LEGACY_PREFIX = "sha256"

_WEAK_SECRETS = {"", "change-me-please", "changeme", "secret", "password"}
_bearer = HTTPBearer(auto_error=False)
_USERS_LOCK = threading.RLock()


def _resolve_token_secret() -> str:
    """Return the token signing secret.

    * ``AUTH_TOKEN_SECRET`` is used when set (must not be a known weak value).
    * Otherwise a random secret is generated once and stored next to the data
      files, so tokens survive restarts without shipping a guessable default.
    """
    configured = os.environ.get("AUTH_TOKEN_SECRET")
    if configured is not None and configured.strip():
        if configured.strip().lower() in _WEAK_SECRETS or len(configured) < 16:
            raise RuntimeError(
                "AUTH_TOKEN_SECRET is a known weak value or shorter than 16 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return configured
    if SECRET_FILE.exists():
        stored = SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(stored) >= 32:
            return stored
    generated = secrets.token_urlsafe(48)
    atomic_write_text(SECRET_FILE, generated + "\n", mode=0o600)
    logger.warning(
        "AUTH_TOKEN_SECRET is not set; generated a random secret at %s. "
        "Set AUTH_TOKEN_SECRET explicitly in production.",
        SECRET_FILE,
    )
    return generated


TOKEN_SECRET = _resolve_token_secret()


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #

def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"{_HASH_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest}"


def _needs_rehash(stored: str) -> bool:
    if not stored.startswith(f"{_HASH_PREFIX}$"):
        return True
    try:
        return int(stored.split("$", 3)[1]) < PBKDF2_ITERATIONS
    except (ValueError, IndexError):
        return True


def _verify_password(password: str, stored: str) -> bool:
    if stored.startswith(f"{_HASH_PREFIX}$"):
        try:
            _, iterations, salt, digest = stored.split("$", 3)
            calc = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
            ).hex()
        except (ValueError, binascii.Error):
            return False
        return hmac.compare_digest(calc, digest)
    if stored.startswith(f"{_LEGACY_PREFIX}$"):
        try:
            _, salt, digest = stored.split("$", 2)
        except ValueError:
            return False
        calc = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return hmac.compare_digest(calc, digest)
    # Plain-text value from a hand-edited users.json: accepted once, then
    # upgraded to a real hash on the next successful login.
    return hmac.compare_digest(stored.encode("utf-8"), password.encode("utf-8"))


_DUMMY_HASH = _hash_password(secrets.token_urlsafe(12))


# --------------------------------------------------------------------------- #
# User store
# --------------------------------------------------------------------------- #

def _load_users() -> Dict[str, Dict[str, Any]]:
    if not USER_FILE.exists():
        return {}
    try:
        with USER_FILE.open("r", encoding="utf-8-sig") as f:
            payload = json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid users.json: {exc}") from exc
    users: Dict[str, Dict[str, Any]] = {}
    if isinstance(payload, dict):
        # Oldest format ({"email": "password"}): every account was an administrator.
        for email, password in payload.items():
            email = str(email).strip()
            if not email or not isinstance(password, str) or not password:
                continue
            users[email.lower()] = {"email": email, "password": password, "role": "admin"}
    elif isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            email = entry.get("email")
            password = entry.get("password_hash") or entry.get("password")
            if not isinstance(email, str) or not email.strip() or not isinstance(password, str) or not password:
                continue
            email = email.strip()
            users[email.lower()] = {"email": email, "password": password, "role": _normalize_role(entry, email)}
    return users


def _normalize_role(entry: Dict[str, Any], email: str) -> str:
    """Read the role of a users.json entry; anything unrecognised gets the least privilege."""
    raw = entry.get("role") or entry.get("type")
    role = str(raw).strip().lower() if raw is not None else ""
    if role in VALID_ROLES:
        return role
    logger.warning(
        "users.json: account %s has %s role %r; treating it as 'general'. "
        "Set \"role\": \"admin\" explicitly for administrators.",
        email,
        "an unknown" if role else "no",
        raw,
    )
    return "general"


def _save_users(users: Dict[str, Dict[str, Any]]) -> None:
    sorted_items = sorted(users.items(), key=lambda item: item[0])
    payload = [
        {"email": item[1]["email"], "password": item[1]["password"], "role": item[1].get("role", "general")}
        for item in sorted_items
    ]
    atomic_write_text(USER_FILE, json.dumps(payload, indent=2) + "\n", mode=0o600)


# --------------------------------------------------------------------------- #
# Login throttling (in-memory, per email)
# --------------------------------------------------------------------------- #

MAX_FAILED_LOGINS = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60
# Bound memory use even if an attacker cycles through many different emails.
_MAX_TRACKED_KEYS = 10_000
_failed_logins: Dict[str, List[float]] = {}
_throttle_lock = threading.Lock()


def _recent_failures(key: str, now: float) -> List[float]:
    cutoff = now - LOCKOUT_WINDOW_SECONDS
    attempts = [t for t in _failed_logins.get(key, []) if t > cutoff]
    if attempts:
        _failed_logins[key] = attempts
    else:
        _failed_logins.pop(key, None)
    return attempts


def _prune_tracked(now: float) -> None:
    if len(_failed_logins) < _MAX_TRACKED_KEYS:
        return
    for key in list(_failed_logins):
        _recent_failures(key, now)
    # Still full of live entries: drop the oldest ones.
    overflow = len(_failed_logins) - _MAX_TRACKED_KEYS // 2
    if overflow > 0:
        oldest = sorted(_failed_logins, key=lambda k: _failed_logins[k][-1])[:overflow]
        for key in oldest:
            _failed_logins.pop(key, None)


def _check_throttle(key: str) -> None:
    now = time.time()
    with _throttle_lock:
        attempts = _recent_failures(key, now)
        if len(attempts) >= MAX_FAILED_LOGINS:
            retry_after = int(attempts[0] + LOCKOUT_WINDOW_SECONDS - now) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed sign-in attempts. Try again later.",
                headers={"Retry-After": str(max(retry_after, 1))},
            )


def _record_failure(key: str) -> None:
    now = time.time()
    with _throttle_lock:
        _prune_tracked(now)
        _failed_logins.setdefault(key, []).append(now)


def _clear_failures(key: str) -> None:
    with _throttle_lock:
        _failed_logins.pop(key, None)


def reset_login_throttle() -> None:
    with _throttle_lock:
        _failed_logins.clear()


def authenticate_user(email: str, password: str) -> Dict[str, Any]:
    email_key = (email or "").strip().lower()
    password = password or ""
    # Password checks run one at a time under this lock, so "check the lockout" and
    # "record the failure" happen together: parallel guesses cannot slip past the
    # limit, and only real failures count (correct logins arriving at once are fine).
    with _USERS_LOCK:
        _check_throttle(email_key)
        users = _load_users()
        user = users.get(email_key)
        # Always run one hash so unknown emails cost the same as wrong passwords.
        valid = _verify_password(password, user["password"] if user else _DUMMY_HASH)
        if not user or not valid:
            _record_failure(email_key)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if _needs_rehash(user["password"]):
            user["password"] = _hash_password(password)
            users[email_key] = user
            _save_users(users)
    _clear_failures(email_key)
    return user


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #

def _sign(payload: str) -> str:
    secret = TOKEN_SECRET.encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_payload(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _decode_payload(token: str) -> Dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return payload


def _credential_fingerprint(user: Dict[str, Any]) -> str:
    """Changes whenever the account is recreated or its password (hash) changes,
    so tokens issued before that stop working."""
    return _sign("fp:" + user["password"])[:16]


def generate_token(email: str) -> str:
    user = _load_users().get(email.strip().lower())
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    payload = {"email": user["email"], "exp": int(time.time()) + TOKEN_TTL, "fp": _credential_fingerprint(user)}
    encoded = _encode_payload(payload)
    signature = _sign(encoded)
    return f"{encoded}.{signature}"


def _validate_token(token: str) -> Dict[str, Any]:
    try:
        encoded, signature = token.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")
    expected = _sign(encoded)
    # Compare bytes: compare_digest() raises TypeError for non-ASCII str (a 500 instead of 401).
    if not hmac.compare_digest(signature.encode("utf-8", "surrogateescape"), expected.encode("ascii")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
    payload = _decode_payload(encoded)
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return payload


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Dict[str, Any]:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    payload = _validate_token(credentials.credentials)
    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing email")
    users = _load_users()
    user = users.get(email.lower())
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    fingerprint = payload.get("fp")
    if not isinstance(fingerprint, str) or not hmac.compare_digest(
        fingerprint.encode("utf-8", "surrogateescape"), _credential_fingerprint(user).encode("ascii")
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid; sign in again")
    return {"email": user["email"], "role": user.get("role", "general")}


def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges are required for this action",
        )
    return user


# --------------------------------------------------------------------------- #
# User management
# --------------------------------------------------------------------------- #

def list_users() -> List[Dict[str, str]]:
    users = _load_users()
    return [{"email": u["email"], "role": u.get("role", "general")} for u in users.values()]


def create_user(email: str, password: str, role: str) -> Dict[str, str]:
    if not (email or "").strip() or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email and password are required")
    try:
        email = normalize_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    email_key = email.lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}"
        )
    with _USERS_LOCK:
        users = _load_users()
        if email_key in users:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
        users[email_key] = {"email": email, "password": _hash_password(password), "role": role}
        _save_users(users)
    return {"email": email, "role": role}


def delete_user(email: str, *, acting_email: Optional[str] = None) -> None:
    email_key = (email or "").strip().lower()
    with _USERS_LOCK:
        users = _load_users()
        target = users.get(email_key)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if acting_email and acting_email.strip().lower() == email_key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own account")
        if target.get("role") == "admin":
            admins = [u for u in users.values() if u.get("role") == "admin"]
            if len(admins) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the last admin account"
                )
        users.pop(email_key)
        _save_users(users)


def bootstrap_admin_from_env() -> Optional[str]:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD if no users exist."""
    email = (os.environ.get("ADMIN_EMAIL") or "").strip()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    with _USERS_LOCK:
        if _load_users():
            return None
        try:
            create_user(email, password, "admin")
        except HTTPException as exc:
            # Do not crash-loop the container: log clearly and keep serving (the CLI still works).
            logger.error("ADMIN_EMAIL/ADMIN_PASSWORD not used: %s", exc.detail)
            return None
    logger.info("Created initial admin account for %s", email)
    return email
