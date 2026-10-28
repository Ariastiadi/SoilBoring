"""Integrity seal of issued documents: approved client reports and authorised laboratory results.

At issue the document's content is written as canonical JSON (keys sorted, no spaces, UTF-8,
no NaN) together with what was issued, by whom and when, and hashed with SHA-256 (FIPS 180-4).
The seal keeps that content, so the hash can be checked again later, and a short code (the
first 12 hex digits, grouped as XXXX-XXXX-XXXX) printed with a QR code on the document.

Anyone can open ``/verify/<code or hash>`` without signing in: it shows only the kind of
document, its number and title, the project, the issuing company, the date and whether it is
valid, superseded by a newer issue, or revoked (withdrawn). No technical data is shown.

Documents: ``seal/<hash>.json`` (the seal), ``seal-code/<CODE>`` (code -> hash) and
``seal-family/<entity>/<family>.json`` (the hashes issued for one document, oldest first).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import docstore

_HASH = re.compile(r"^[a-f0-9]{64}$")
_CODE = re.compile(r"^[A-F0-9]{12,16}$")
_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LOCK = "seals"

STATUSES = ("valid", "superseded", "revoked")


def canonical(obj: Any) -> str:
    """Canonical JSON: sorted keys, compact separators, UTF-8 text; NaN/Infinity are refused."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _seal_doc(hash_: str) -> str:
    return f"seal/{hash_}.json"


def _family_doc(entity: str, family: str) -> str:
    if not _SAFE.match(entity) or not _SAFE.match(family):
        raise ValueError("invalid seal family")
    return f"seal-family/{entity}/{family}.json"


def _read(hash_: str) -> Optional[Dict[str, Any]]:
    if not _HASH.match(hash_ or ""):
        return None
    text = docstore.read_text(_seal_doc(hash_))
    return json.loads(text) if text else None


def _write(seal: Dict[str, Any]) -> None:
    docstore.write_text(_seal_doc(seal["hash"]), json.dumps(seal, ensure_ascii=False, separators=(",", ":")))


def family(entity: str, family_id: str) -> List[Dict[str, Any]]:
    """Seals issued for one document, oldest first."""
    text = docstore.read_text(_family_doc(entity, family_id))
    hashes = json.loads(text) if text else []
    return [s for s in (_read(h) for h in hashes) if s]


def finite(obj: Any) -> Any:
    """The same data with NaN/Infinity replaced by None (canonical JSON refuses them)."""
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else None
    if isinstance(obj, dict):
        return {str(k): finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [finite(v) for v in obj]
    return obj


def issue(document_type: str, entity: str, record_id: str, family_id: str, meta: Dict[str, str],
          issued_by: str, content: Dict[str, Any]) -> Dict[str, Any]:
    """Seal the content; earlier seals of the same document become superseded."""
    content = finite(content)
    issued_at = _now()
    sealed = {
        "document_type": document_type, "number": meta.get("number", ""), "title": meta.get("title", ""),
        "project": meta.get("project", ""), "issuer": meta.get("issuer", ""), "issued_at": issued_at,
        "issued_by": issued_by, "content": content,
    }
    hash_ = digest(sealed)
    with docstore.lock(LOCK):
        code = hash_[:12].upper()
        taken = docstore.read_text(f"seal-code/{code}")
        if taken and taken.strip() != hash_:
            code = hash_[:16].upper()
        seal = {
            "hash": hash_, "code": code, "document_type": document_type, "entity": entity, "record_id": record_id,
            "family": family_id, "number": sealed["number"], "title": sealed["title"], "project": sealed["project"],
            "issuer": sealed["issuer"], "issued_at": issued_at, "issued_by": issued_by, "status": "valid",
            "superseded_by": "", "revoked_at": "", "sealed": sealed,
        }
        hashes: List[str] = []
        for earlier in family(entity, family_id):
            hashes.append(earlier["hash"])
            if earlier.get("status") != "superseded":
                earlier["status"] = "superseded"
                earlier["superseded_by"] = hash_
                _write(earlier)
        _write(seal)
        docstore.write_text(f"seal-code/{code}", hash_)
        docstore.write_text(_family_doc(entity, family_id), json.dumps(hashes + [hash_]))
    return seal


def revoke(entity: str, family_id: str) -> int:
    """Withdraw the valid seal(s) of a document (approval reopened, authorisation withdrawn)."""
    count = 0
    with docstore.lock(LOCK):
        for seal in family(entity, family_id):
            if seal.get("status") == "valid":
                seal["status"] = "revoked"
                seal["revoked_at"] = _now()
                _write(seal)
                count += 1
    return count


def lookup(token: str) -> Optional[Dict[str, Any]]:
    """A seal by its full hash or its short code (dashes, spaces and case ignored)."""
    raw = (token or "").strip()
    if _HASH.match(raw.lower()):
        return _read(raw.lower())
    code = re.sub(r"[\s-]", "", raw).upper()
    if not _CODE.match(code):
        return None
    hash_ = (docstore.read_text(f"seal-code/{code}") or "").strip()
    return _read(hash_) if hash_ else None


def intact(seal: Dict[str, Any]) -> bool:
    """The stored content still gives the hash it was issued with."""
    try:
        return digest(seal.get("sealed")) == seal.get("hash")
    except (TypeError, ValueError):
        return False


def public_view(seal: Dict[str, Any]) -> Dict[str, Any]:
    """What the public verify page shows: no technical data."""
    newer = _read(seal.get("superseded_by") or "") if seal.get("status") == "superseded" else None
    return {
        "document_type": seal.get("document_type", ""),
        "number": seal.get("number", ""),
        "title": seal.get("title", ""),
        "project": seal.get("project", ""),
        "issuer": seal.get("issuer", ""),
        "date": str(seal.get("issued_at", ""))[:10],
        "status": seal.get("status") if intact(seal) else "invalid",
        "code": format_code(seal.get("code", "")),
        "hash": seal.get("hash", ""),
        "revoked_on": str(seal.get("revoked_at") or "")[:10],
        "superseded_by": format_code(newer["code"]) if newer else "",
    }


def summary(seal: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Seal facts for signed-in staff (record views)."""
    if not seal:
        return None
    out = public_view(seal)
    out.update({"issued_at": seal.get("issued_at", ""), "issued_by": seal.get("issued_by", ""), "intact": intact(seal)})
    return out
