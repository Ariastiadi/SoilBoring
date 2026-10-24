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

from . import docstore
from .models import normalize_email


logger = logging.getLogger(__name__)

USERS_DOC = "users.json"
SECRET_DOC = ".token_secret"
USER_FILE = docstore.path_for(USERS_DOC)  # only meaningful in file mode
SECRET_FILE = docstore.path_for(SECRET_DOC)
TOKEN_TTL = int(os.environ.get("AUTH_TOKEN_TTL", "28800"))  # 8 hours
VALID_ROLES = {"admin", "general"}
MIN_PASSWORD_LENGTH = 8

# Password hashing: PBKDF2-HMAC-SHA256 (stdlib, no extra dependency).
PBKDF2_ITERATIONS = 600_000
_HASH_PREFIX = "pbkdf2_sha256"
_LEGACY_PREFIX = "sha256"

_WEAK_SECRETS = {"", "change-me-please", "changeme", "secret", "password"}
_bearer = HTTPBearer(auto_error=False)


def _resolve_token_secret() -> str:
    """Return the token signing secret.

    * ``AUTH_TOKEN_SECRET`` is used when set (must not be a known weak value).
    * Otherwise a random secret is generated once and stored with the data (file or
      database), so tokens survive restarts without shipping a guessable default.
    """
    configured = os.environ.get("AUTH_TOKEN_SECRET")
    if configured is not None and configured.strip():
        if configured.strip().lower() in _WEAK_SECRETS or len(configured) < 16:
            raise RuntimeError(
                "AUTH_TOKEN_SECRET is a known weak value or shorter than 16 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return configured
    with docstore.lock(SECRET_DOC):
        stored = (docstore.read_text(SECRET_DOC) or "").strip()
        if len(stored) >= 32:
            return stored
        generated = secrets.token_urlsafe(48)
        docstore.write_text(SECRET_DOC, generated + "\n", private=True)
    logger.warning(
        "AUTH_TOKEN_SECRET is not set; generated a random secret and stored it with the data (%s).",
        "database" if docstore.USE_DATABASE else SECRET_FILE,
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

# Two-step verification and recovery codes, kept with the account in users.json.
_EXTRA_FIELDS = ("totp_secret", "totp_enabled", "totp_pending", "totp_last", "recovery_codes")


def _load_users() -> Dict[str, Dict[str, Any]]:
    text = docstore.read_text(USERS_DOC)
    if text is None or not text.strip():
        return {}
    try:
        payload = json.loads(text)
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
            user = {"email": email, "password": password, "role": _normalize_role(entry, email)}
            for field in _EXTRA_FIELDS:
                if field in entry:
                    user[field] = entry[field]
            users[email.lower()] = user
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
    payload = []
    for _, user in sorted_items:
        entry = {"email": user["email"], "password": user["password"], "role": user.get("role", "general")}
        entry.update({k: user[k] for k in _EXTRA_FIELDS if user.get(k) not in (None, "", [], False)})
        payload.append(entry)
    docstore.write_text(USERS_DOC, json.dumps(payload, indent=2) + "\n", private=True)


# --------------------------------------------------------------------------- #
# Login throttling (per email), stored with the data
# --------------------------------------------------------------------------- #
# Kept in the document store (file or database) instead of process memory, so the limit
# also holds when several app instances run at once (serverless hosts such as Vercel).

MAX_FAILED_LOGINS = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60
THROTTLE_DOC = "login_throttle.json"
# Bound the document even if an attacker cycles through many different emails.
_MAX_TRACKED_KEYS = 10_000


def _load_throttle() -> Dict[str, List[float]]:
    text = docstore.read_text(THROTTLE_DOC)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): [float(t) for t in v if isinstance(t, (int, float))] for k, v in data.items() if isinstance(v, list)}


def _save_throttle(data: Dict[str, List[float]]) -> None:
    docstore.write_text(THROTTLE_DOC, json.dumps(data, separators=(",", ":")), private=True)


def _live(data: Dict[str, List[float]], now: float) -> Dict[str, List[float]]:
    def cutoff(key: str) -> float:
        return now - (3600 if key.startswith("reset:") else LOCKOUT_WINDOW_SECONDS)

    live = {k: [t for t in v if t > cutoff(k)] for k, v in data.items()}
    live = {k: v for k, v in live.items() if v}
    overflow = len(live) - _MAX_TRACKED_KEYS
    if overflow > 0:
        for key in sorted(live, key=lambda k: live[k][-1])[: overflow + _MAX_TRACKED_KEYS // 2]:
            live.pop(key, None)
    return live


def _check_throttle(key: str) -> None:
    now = time.time()
    attempts = _live(_load_throttle(), now).get(key, [])
    if len(attempts) >= MAX_FAILED_LOGINS:
        retry_after = int(attempts[0] + LOCKOUT_WINDOW_SECONDS - now) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(max(retry_after, 1))},
        )


def _record_failure(key: str) -> None:
    now = time.time()
    with docstore.lock(THROTTLE_DOC):
        data = _live(_load_throttle(), now)
        data.setdefault(key, []).append(now)
        _save_throttle(_live(data, now))


def _clear_failures(key: str) -> None:
    with docstore.lock(THROTTLE_DOC):
        data = _load_throttle()
        if key in data:
            data.pop(key)
            _save_throttle(data)


def _tracked_count() -> int:
    return len(_load_throttle())


def reset_login_throttle() -> None:
    docstore.delete(THROTTLE_DOC)


class OTPRequired(HTTPException):
    """Password was right, but the account needs its authentication code too."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="otp_required")


def _login_lock(email_key: str) -> str:
    """Lock name for one account's sign-in attempts (64 buckets, so the lock table stays small).

    Attempts for the same email run one at a time, so "check the lockout" and "record the
    failure" cannot be raced by parallel guesses; other accounts are not held up, and the
    slow password hash never runs under the global users.json lock.
    """
    bucket = int(hashlib.sha256(email_key.encode("utf-8")).hexdigest(), 16) % 64
    return f"login:{bucket}"


def authenticate_user(email: str, password: str, otp: Optional[str] = None, *, check_otp: bool = True) -> Dict[str, Any]:
    email_key = (email or "").strip().lower()
    password = password or ""
    # Failures are recorded inside the lock but raised after it, so the record is committed
    # (in database mode an exception inside the lock would roll it back).
    failure: Optional[HTTPException] = None
    user: Optional[Dict[str, Any]] = None
    with docstore.lock(_login_lock(email_key)):
        _check_throttle(email_key)
        user = _load_users().get(email_key)
        # Always run one hash so unknown emails cost the same as wrong passwords.
        valid = _verify_password(password, user["password"] if user else _DUMMY_HASH)
        if not user or not valid:
            _record_failure(email_key)
            failure = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        else:
            needs_otp = check_otp and bool(user.get("totp_enabled"))
            if needs_otp and not (otp or "").strip():
                raise OTPRequired()
            rehash = _hash_password(password) if _needs_rehash(user["password"]) else None
            if needs_otp or rehash:
                # Short write under the global lock: the code is checked against the stored
                # state (last used step, remaining recovery codes) and the change saved together.
                with docstore.lock(USERS_DOC):
                    users = _load_users()
                    current = users.get(email_key)
                    if current is None or current["password"] != user["password"]:
                        failure = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
                    elif needs_otp and not _accept_second_factor(current, otp or ""):
                        failure = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication code")
                    else:
                        if rehash:
                            current["password"] = rehash
                        _save_users(users)
                        user = current
                if failure is not None:
                    _record_failure(email_key)
    if failure is not None:
        raise failure
    assert user is not None
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
    if payload.get("purpose"):
        # Password-reset links are signed the same way but are never sessions.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
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
    return {"email": user["email"], "role": user.get("role", "general"), "totp_enabled": bool(user.get("totp_enabled"))}


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

def list_users() -> List[Dict[str, Any]]:
    users = _load_users()
    return [
        {"email": u["email"], "role": u.get("role", "general"), "totp_enabled": bool(u.get("totp_enabled"))}
        for u in users.values()
    ]


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
    with docstore.lock(USERS_DOC):
        users = _load_users()
        if email_key in users:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
        users[email_key] = {"email": email, "password": _hash_password(password), "role": role}
        _save_users(users)
    return {"email": email, "role": role}


def _check_new_password(password: str) -> None:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )


def set_password(email: str, new_password: str) -> None:
    """Replace a user's password. Existing sessions of that user stop working."""
    _check_new_password(new_password)
    email_key = (email or "").strip().lower()
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = users.get(email_key)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user["password"] = _hash_password(new_password)
        _save_users(users)
    # A reset usually follows a lockout; the new password must work right away.
    _clear_failures(email_key)


def change_own_password(email: str, current_password: str, new_password: str) -> None:
    """Self-service change; the current password is checked like a sign-in (same lockout)."""
    _check_new_password(new_password)
    if current_password == new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a password you have not used just now")
    try:
        authenticate_user(email, current_password, check_otp=False)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            # 400, not 401: the session is fine, only the typed password is wrong.
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect") from exc
        raise
    set_password(email, new_password)


def delete_user(email: str, *, acting_email: Optional[str] = None) -> None:
    email_key = (email or "").strip().lower()
    with docstore.lock(USERS_DOC):
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


def setup_needed() -> bool:
    """True while no account exists yet (a fresh deployment)."""
    return not _load_users()


def first_run_setup_enabled() -> bool:
    return (os.environ.get("ALLOW_FIRST_RUN_SETUP") or "true").strip().lower() not in {"0", "false", "no", "off"}


def create_first_admin(email: str, password: str) -> Dict[str, str]:
    """First-run setup from the web UI: the first account becomes an admin.

    Only possible while no account exists. If ADMIN_EMAIL is set, only that address may be
    used; ALLOW_FIRST_RUN_SETUP=false turns the feature off (then use ADMIN_PASSWORD or the CLI).
    """
    if not first_run_setup_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="First-run setup is disabled")
    allowed = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    with docstore.lock(USERS_DOC):
        if _load_users():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup is already done; please sign in")
        if allowed and (email or "").strip().lower() != allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Use the admin email configured on the server (ADMIN_EMAIL)"
            )
        created = create_user(email, password, "admin")
    logger.info("Created initial admin account for %s via first-run setup", created["email"])
    return created


def bootstrap_admin_from_env() -> Optional[str]:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD if no users exist."""
    email = (os.environ.get("ADMIN_EMAIL") or "").strip()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    with docstore.lock(USERS_DOC):
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


# --------------------------------------------------------------------------- #
# Two-step verification (TOTP, RFC 6238) and recovery codes
# --------------------------------------------------------------------------- #

TOTP_STEP = 30
TOTP_DIGITS = 6
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def _totp_at(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % (10 ** TOTP_DIGITS)
    return f"{value:0{TOTP_DIGITS}d}"


def _totp_match(secret_b32: str, code: str, last_step: int = -1, now: Optional[float] = None) -> Optional[int]:
    """Step number of a valid code (±1 step of clock drift), or None. Used steps are refused."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != TOTP_DIGITS:
        return None
    step = int((now if now is not None else time.time()) // TOTP_STEP)
    for candidate in (step - 1, step, step + 1):
        if candidate > last_step and hmac.compare_digest(_totp_at(secret_b32, candidate), code):
            return candidate
    return None


RECOVERY_ITERATIONS = 60_000


def _clean_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _hash_recovery(code: str) -> str:
    """Salted PBKDF2, so a leaked users.json does not reveal the codes."""
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", _clean_code(code).encode("utf-8"), bytes.fromhex(salt), RECOVERY_ITERATIONS).hex()
    return f"pbkdf2${salt}${digest}"


def _recovery_matches(code: str, stored: str) -> bool:
    cleaned = _clean_code(code)
    if stored.startswith("pbkdf2$"):
        try:
            _, salt, digest = stored.split("$", 2)
            calc = hashlib.pbkdf2_hmac("sha256", cleaned.encode("utf-8"), bytes.fromhex(salt), RECOVERY_ITERATIONS).hex()
        except ValueError:
            return False
        return hmac.compare_digest(calc, digest)
    # First version (unsalted SHA-256).
    return hmac.compare_digest(hashlib.sha256(("soilboring-recovery:" + cleaned).encode("utf-8")).hexdigest(), stored)


def _new_recovery_codes() -> List[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))  # 60 bits
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def _use_recovery_code(user: Dict[str, Any], code: str) -> bool:
    if len(_clean_code(code)) < 8:
        return False
    stored = list(user.get("recovery_codes") or [])
    for index, value in enumerate(stored):
        if _recovery_matches(code, value):
            del stored[index]
            user["recovery_codes"] = stored
            return True
    return False


def _accept_second_factor(user: Dict[str, Any], code: str) -> bool:
    """A current authenticator code, or one unused recovery code (then used up)."""
    secret = user.get("totp_secret")
    if secret:
        step = _totp_match(secret, code, int(user.get("totp_last") or -1))
        if step is not None:
            user["totp_last"] = step
            return True
    return _use_recovery_code(user, code)


def _user_or_404(users: Dict[str, Dict[str, Any]], email: str) -> Dict[str, Any]:
    user = users.get((email or "").strip().lower())
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def start_totp_setup(email: str, issuer: str) -> Dict[str, str]:
    """New secret waiting for its first code; the account keeps working as before until then."""
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = _user_or_404(users, email)
        if user.get("totp_enabled"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-step verification is already on")
        user["totp_pending"] = secret
        _save_users(users)
    from urllib.parse import quote

    label = quote(f"{issuer}:{user['email']}")
    uri = f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP}"
    return {"secret": secret, "otpauth_uri": uri}


def confirm_totp_setup(email: str, code: str) -> List[str]:
    """Turns two-step verification on; returns fresh recovery codes (shown once)."""
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = _user_or_404(users, email)
        pending = user.get("totp_pending")
        if not pending:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start the setup first")
        step = _totp_match(pending, code)
        if step is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The code is not correct; check the time on your phone")
        codes = _new_recovery_codes()
        user.update({
            "totp_secret": pending,
            "totp_enabled": True,
            "totp_last": step,
            "recovery_codes": [_hash_recovery(c) for c in codes],
        })
        user.pop("totp_pending", None)
        _save_users(users)
    return codes


def disable_totp(email: str) -> None:
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = _user_or_404(users, email)
        # Recovery codes go too: a lost code sheet must not outlive the phone it backed up.
        for field in ("totp_secret", "totp_enabled", "totp_pending", "totp_last", "recovery_codes"):
            user.pop(field, None)
        _save_users(users)


def regenerate_recovery_codes(email: str) -> List[str]:
    codes = _new_recovery_codes()
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = _user_or_404(users, email)
        user["recovery_codes"] = [_hash_recovery(c) for c in codes]
        _save_users(users)
    return codes


def recovery_codes_left(email: str) -> int:
    user = _load_users().get((email or "").strip().lower()) or {}
    return len(user.get("recovery_codes") or [])


def reset_with_recovery_code(email: str, code: str, new_password: str, otp: Optional[str] = None) -> None:
    """Forgotten password: a recovery code proves the account owner.

    With two-step verification on, the current authenticator code is needed as well, so
    the code sheet alone is never enough to take over the account (lost phone: an admin
    turns two-step verification off first).
    """
    _check_new_password(new_password)
    email_key = (email or "").strip().lower()
    bad = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email, recovery code or authentication code is not correct")
    ok = False
    with docstore.lock(_login_lock(email_key)):
        _check_throttle(email_key)
        with docstore.lock(USERS_DOC):
            users = _load_users()
            user = users.get(email_key)
            if user and user.get("totp_enabled"):
                step = _totp_match(user.get("totp_secret") or "", otp or "", int(user.get("totp_last") or -1))
                if step is not None and _use_recovery_code(user, code or ""):
                    user["totp_last"] = step
                    ok = True
            elif user and _use_recovery_code(user, code or ""):
                ok = True
            if ok and user is not None:
                user["password"] = _hash_password(new_password)
                _save_users(users)
        if not ok:
            _record_failure(email_key)  # committed: raised only after the locks below
    if not ok:
        raise bad
    _clear_failures(email_key)


def account_uses_totp(email: str) -> bool:
    user = _load_users().get((email or "").strip().lower()) or {}
    return bool(user.get("totp_enabled"))


def confirm_password(email: str, password: str) -> None:
    """Re-check the password of a signed-in user before a sensitive change (400, not 401,
    so a typo does not look like an expired session)."""
    try:
        authenticate_user(email, password, check_otp=False)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect") from exc
        raise


def verify_current_totp(email: str, code: str) -> None:
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = users.get((email or "").strip().lower())
        step = _totp_match(user.get("totp_secret") or "", code or "", int(user.get("totp_last") or -1)) if user else None
        if step is None or user is None:
            ok = False
        else:
            user["totp_last"] = step
            _save_users(users)
            ok = True
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The authentication code is not correct")


# --------------------------------------------------------------------------- #
# Password reset by email (only when SMTP is configured)
# --------------------------------------------------------------------------- #

RESET_TTL = 30 * 60
RESET_MAILS_PER_HOUR = 3


def allow_reset_email(email: str) -> bool:
    """At most RESET_MAILS_PER_HOUR reset mails per address (shared across instances)."""
    key = "reset:" + (email or "").strip().lower()
    now = time.time()
    with docstore.lock(THROTTLE_DOC):
        data = _load_throttle()
        recent = [t for t in data.get(key, []) if t > now - 3600]
        if len(recent) >= RESET_MAILS_PER_HOUR:
            return False
        data[key] = recent + [now]
        _save_throttle(_live(data, now))
    return True


def make_reset_token(email: str) -> Optional[str]:
    """Signed, 30-minute, single-use link token (it dies once the password changes)."""
    user = _load_users().get((email or "").strip().lower())
    if not user:
        return None
    payload = {"email": user["email"], "exp": int(time.time()) + RESET_TTL, "fp": _credential_fingerprint(user), "purpose": "reset"}
    encoded = _encode_payload(payload)
    return f"{encoded}.{_sign(encoded)}"


def reset_with_token(token: str, new_password: str) -> str:
    _check_new_password(new_password)
    invalid = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired")
    try:
        encoded, signature = (token or "").rsplit(".", 1)
    except ValueError:
        raise invalid
    if not hmac.compare_digest(signature.encode("utf-8", "surrogateescape"), _sign(encoded).encode("ascii")):
        raise invalid
    try:
        payload = _decode_payload(encoded)
    except HTTPException:
        raise invalid
    if payload.get("purpose") != "reset" or not isinstance(payload.get("exp"), (int, float)) or payload["exp"] < time.time():
        raise invalid
    email_key = str(payload.get("email") or "").strip().lower()
    with docstore.lock(USERS_DOC):
        users = _load_users()
        user = users.get(email_key)
        if not user or not hmac.compare_digest(str(payload.get("fp")), _credential_fingerprint(user)):
            raise invalid
        user["password"] = _hash_password(new_password)
        _save_users(users)
    _clear_failures(email_key)
    return user["email"]
