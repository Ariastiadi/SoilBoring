"""Records of the business modules (clients, projects, quotations, contracts, field work,
laboratory, analyses, reports, invoices): one document per record (``rec/<entity>/<id>.json``),
validated against :mod:`entities`.

Attachments are kept as separate documents (``file-<id>.b64``) like borehole photos.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import re
import secrets
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from . import docstore
from .entities import ENTITIES, Entity, F

MAX_FILE_BYTES = 5 * 1024 * 1024
FILE_TYPES = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG",
    "text/csv": b"",
    "text/plain": b"",
    "application/zip": b"PK",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK",
}
_ID = re.compile(r"^[a-f0-9]{16,24}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


class RecordError(ValueError):
    """Input that cannot be stored (HTTP 422)."""


class ConflictError(Exception):
    """Changed by someone else, or still referenced (HTTP 409)."""


class NotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc(entity: str, record_id: str) -> str:
    if not _ID.match(record_id or ""):
        raise NotFound(record_id)
    return f"rec/{entity}/{record_id}.json"


def _lock_name(entity: str) -> str:
    return f"rec/{entity}"


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def list_records(entity: str) -> List[Dict[str, Any]]:
    out = []
    for text in docstore.list_prefix(f"rec/{entity}/").values():
        try:
            out.append(json.loads(text))
        except ValueError:
            continue
    return out


def get_record(entity: str, record_id: str) -> Dict[str, Any]:
    text = docstore.read_text(_doc(entity, record_id))
    if text is None:
        raise NotFound(record_id)
    return json.loads(text)


def get_singleton(entity: str) -> Optional[Dict[str, Any]]:
    items = list_records(entity)
    return items[0] if items else None


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _finite(value: Any, f: F, where: str) -> Optional[float]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if isinstance(value, bool):
        raise RecordError(f"{where} must be a number")
    try:
        number = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"{where} must be a number") from exc
    if not math.isfinite(number):
        raise RecordError(f"{where} must be a number")
    if f.min is not None and number < f.min:
        raise RecordError(f"{where} must be at least {f.min:g}")
    if f.max is not None and number > f.max:
        raise RecordError(f"{where} must be at most {f.max:g}")
    if f.type in ("int",):
        number = float(int(number))
    return round(number, 6)


def _text(value: Any, limit: int, where: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)):
        raise RecordError(f"{where} must be text")
    text = str(value).replace("\x00", "").strip()
    if len(text) > limit:
        raise RecordError(f"{where} must be at most {limit} characters")
    return text


def _option_values(f: F) -> List[str]:
    return [str(o[0]) for o in (f.options or [])]


def _clean_value(f: F, value: Any, where: str, record: Dict[str, Any], refs: Callable[[str, str], bool]) -> Any:
    t = f.type
    if t in ("number", "int", "money", "percent"):
        return _finite(value, f, where)
    if t == "text":
        return _text(value, f.maxlen, where)
    if t == "longtext":
        return _text(value, f.maxlen, where)
    if t == "email":
        text = _text(value, 254, where)
        if text and not _EMAIL.match(text):
            raise RecordError(f"{where}: enter a valid email address (name@domain)")
        return text
    if t == "user":
        return _text(value, 254, where).lower()
    if t == "date":
        text = _text(value, 10, where)
        if text:
            try:
                date.fromisoformat(text)
            except ValueError as exc:
                raise RecordError(f"{where} is not a valid date") from exc
        return text
    if t == "bool":
        return bool(value)
    if t == "select":
        text = _text(value, 60, where)
        if text and text not in _option_values(f):
            raise RecordError(f"{where}: choose one of the listed options")
        if text and f.options_filter:
            group = record.get(f.options_filter)
            allowed = [str(o[0]) for o in (f.options or []) if len(o) < 3 or o[2] == group]
            if text not in allowed:
                raise RecordError(f"{where}: this option does not belong to the chosen {f.options_filter}")
        return text
    if t == "multiselect":
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise RecordError(f"{where}: choose from the list")
        allowed = _option_values(f)
        out = []
        for item in value:
            if str(item) not in allowed:
                raise RecordError(f"{where}: choose one of the listed options")
            if str(item) not in out:
                out.append(str(item))
        return out
    if t == "ref":
        text = _text(value, 40, where)
        if text and (not _ID.match(text) or not refs(f.ref or "", text)):
            raise RecordError(f"{where}: the chosen record no longer exists")
        return text
    if t == "items":
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise RecordError(f"{where} must be a list")
        if len(value) > f.max_items:
            raise RecordError(f"{where}: at most {f.max_items} rows")
        rows = []
        for i, row in enumerate(value, start=1):
            if not isinstance(row, dict):
                raise RecordError(f"{where} row {i} is not valid")
            clean: Dict[str, Any] = {}
            for sub in f.fields or []:
                sub_where = f"{where} row {i}, {sub.label}"
                v = _clean_value(sub, row.get(sub.name), sub_where, clean, refs)
                if sub.required and v in (None, "", []):
                    raise RecordError(f"{sub_where} is required")
                clean[sub.name] = v
            rows.append(clean)
        return rows
    if t == "files":
        if value in (None, ""):
            return []
        if not isinstance(value, list) or len(value) > 30:
            raise RecordError(f"{where}: at most 30 files")
        files = []
        for item in value:
            file_id = str((item or {}).get("id", "")) if isinstance(item, dict) else ""
            meta = file_meta(file_id)
            if meta is None:
                raise RecordError(f"{where}: a file was not found; upload it again")
            files.append(meta)
        return files
    if t == "json":
        if f.readonly:
            return None
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise RecordError(f"{where} is not valid")
        if f.variants_by and f.variants is not None:
            variant = f.variants.get(str(record.get(f.variants_by) or ""), [])
            clean = {}
            for sub in variant:
                clean[sub.name] = _clean_value(sub, value.get(sub.name), f"{where}, {sub.label}", clean, refs)
            return clean
        text = json.dumps(value)
        if len(text) > 200_000:
            raise RecordError(f"{where} is too large")
        return json.loads(text)
    raise RecordError(f"{where}: unsupported field")


def clean(entity: Entity, data: Dict[str, Any], refs: Callable[[str, str], bool]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # Fields others depend on (select filters, variants) are cleaned first.
    order = sorted(entity.fields, key=lambda f: 1 if (f.options_filter or f.variants_by) else 0)
    for f in order:
        if f.readonly:
            continue
        value = data.get(f.name, f.default) if f.name in data else f.default
        value = _clean_value(f, value, f.label, out, refs)
        if f.required and value in (None, "", []):
            if f.name == entity.number_field:
                continue
            raise RecordError(f"{f.label} is required")
        out[f.name] = value
    return out


# --------------------------------------------------------------------------- #
# Computed fields
# --------------------------------------------------------------------------- #

def _money(value: float) -> float:
    return float(round(value))


def _totals(record: Dict[str, Any], discount: bool) -> None:
    subtotal = sum((row.get("qty") or 0) * (row.get("unit_price") or 0) for row in record.get("items") or [])
    if discount:
        subtotal *= 1 - (record.get("discount_pct") or 0) / 100
    record["subtotal"] = _money(subtotal)
    record["tax"] = _money(subtotal * (record.get("tax_pct") or 0) / 100)
    record["total"] = record["subtotal"] + record["tax"]


def compute(entity: str, record: Dict[str, Any], today: Optional[str] = None) -> Dict[str, Any]:
    if entity == "quotes":
        _totals(record, discount=True)
    elif entity == "invoices":
        _totals(record, discount=False)
        record["pph"] = _money(record["subtotal"] * (record.get("pph_pct") or 0) / 100)
        paid = sum(p.get("amount") or 0 for p in record.get("payments") or [])
        record["paid"] = _money(paid)
        # The client pays the total less the withholding tax it keeps (PPh 23).
        due = record["total"] - record["pph"]
        record["outstanding"] = _money(max(0.0, due - paid))
        today = today or date.today().isoformat()
        if record.get("status") == "cancelled":
            record["outstanding"] = 0.0
            record["payment_status"] = ""
        elif record["outstanding"] <= 0 and due > 0:
            record["payment_status"] = "paid"
        elif paid > 0:
            record["payment_status"] = "partial"
        elif record.get("due_date") and record["due_date"] < today and record.get("status") == "sent":
            record["payment_status"] = "overdue"
        else:
            record["payment_status"] = "unpaid"
    elif entity == "lab_tests":
        res = record.get("results") or {}
        if record.get("test_type") == "atterberg" and res.get("pi") is None and res.get("ll") is not None and res.get("pl") is not None:
            res["pi"] = round(res["ll"] - res["pl"], 2)
        if record.get("test_type") == "grain_size" and res.get("fines") is None and res.get("silt") is not None and res.get("clay") is not None:
            res["fines"] = round(res["silt"] + res["clay"], 2)
        record["results"] = res
    return record


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def _next_number(entity: Entity, when: str) -> str:
    year = (when or date.today().isoformat())[:4]
    counter_doc = f"rec-counter/{entity.name}-{year}"
    with docstore.lock(counter_doc):
        current = int((docstore.read_text(counter_doc) or "0").strip() or 0)
        taken = {str(r.get(entity.number_field)) for r in list_records(entity.name)}
        while True:
            current += 1
            number = f"{entity.number_prefix}-{year}-{current:03d}"
            if number not in taken:
                break
        docstore.write_text(counter_doc, str(current))
    return number


def _exists(entity: str, record_id: str) -> bool:
    try:
        return docstore.read_text(_doc(entity, record_id)) is not None
    except NotFound:
        return False


def _unique_check(entity: Entity, record: Dict[str, Any], record_id: Optional[str]) -> None:
    keys = {"clients": "name", "projects": "code", "contracts": "number", "quotes": "number",
            "invoices": "number", "project_reports": "number", "cpt": "test_id", "rates": "code"}
    key = keys.get(entity.name)
    if not key or not record.get(key):
        return
    wanted = str(record[key]).strip().lower()
    for other in list_records(entity.name):
        if other.get("id") != record_id and str(other.get(key) or "").strip().lower() == wanted:
            found = entity.field(key)
            label = found.label if found else key
            raise ConflictError(f"{label} '{record[key]}' is already used")


def save(entity_name: str, data: Dict[str, Any], user: str, record_id: Optional[str] = None,
         expected_updated_at: Optional[str] = None) -> Dict[str, Any]:
    entity = ENTITIES[entity_name]
    cleaned = clean(entity, data, _exists)
    with docstore.lock(_lock_name(entity_name)):
        before: Dict[str, Any] = {}
        if entity.singleton and record_id is None:
            existing = get_singleton(entity_name)
            if existing:
                record_id = existing["id"]
        if record_id is not None:
            before = get_record(entity_name, record_id)
            if expected_updated_at is not None and before.get("updated_at") != expected_updated_at:
                raise ConflictError(f"{before.get('updated_by') or 'Someone'} changed this record in the meantime; reload before saving")
        if entity.number_field and not cleaned.get(entity.number_field):
            cleaned[entity.number_field] = before.get(entity.number_field) or _next_number(entity, str(cleaned.get("date") or ""))
        _unique_check(entity, cleaned, record_id)
        record = dict(before)
        record.update(cleaned)
        record["id"] = record_id or secrets.token_hex(8)
        if not before:
            record["created_at"] = _now()
            record["created_by"] = user
        record["updated_at"] = _now()
        record["updated_by"] = user
        compute(entity_name, record)
        docstore.write_text(_doc(entity_name, record["id"]), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    # Files removed from the record are deleted.
    kept = {f2["id"] for name in _file_fields(entity) for f2 in record.get(name) or []}
    for name in _file_fields(entity):
        for meta in before.get(name) or []:
            if meta.get("id") not in kept:
                delete_file(meta.get("id", ""))
    return record


def attach_results(entity_name: str, record_id: str, results: Dict[str, Any]) -> Dict[str, Any]:
    """Store server-computed results (engineering analyses) on a saved record."""
    with docstore.lock(_lock_name(entity_name)):
        record = get_record(entity_name, record_id)
        record["results"] = results
        record["summary"] = str(results.get("summary") or "")[:300]
        docstore.write_text(_doc(entity_name, record_id), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return record


def _file_fields(entity: Entity) -> List[str]:
    return [f.name for f in entity.fields if f.type == "files"]


def references_to(entity_name: str, record_id: str) -> List[str]:
    """Records of other kinds that point at this one (they block deleting it)."""
    found = []
    for other in ENTITIES.values():
        ref_fields = [f.name for f in other.fields if f.type == "ref" and f.ref == entity_name]
        item_refs = [(f.name, s.name) for f in other.fields if f.type == "items" for s in (f.fields or []) if s.type == "ref" and s.ref == entity_name]
        if not ref_fields and not item_refs:
            continue
        for record in list_records(other.name):
            hit = any(record.get(name) == record_id for name in ref_fields) or any(
                row.get(sub) == record_id for name, sub in item_refs for row in record.get(name) or [])
            if hit:
                found.append(f"{other.label_one} {record.get(other.title) or record.get('id')}")
    return found


def remove(entity_name: str, record_id: str) -> Dict[str, Any]:
    entity = ENTITIES[entity_name]
    with docstore.lock(_lock_name(entity_name)):
        record = get_record(entity_name, record_id)
        users = references_to(entity_name, record_id)
        if users:
            raise ConflictError(f"Still used by: {', '.join(users[:5])}")
        docstore.delete(_doc(entity_name, record_id))
    for name in _file_fields(entity):
        for meta in record.get(name) or []:
            delete_file(meta.get("id", ""))
    return record


# --------------------------------------------------------------------------- #
# Attachments
# --------------------------------------------------------------------------- #

def _file_doc(file_id: str) -> str:
    if not _ID.match(file_id or ""):
        raise NotFound(file_id)
    return f"file-{file_id}.b64"


def add_file(name: str, content_type: str, data_base64: str, user: str) -> Dict[str, Any]:
    if content_type not in FILE_TYPES:
        raise RecordError("This file type is not accepted (PDF, JPEG, PNG, CSV, TXT, ZIP, XLSX, DOCX)")
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RecordError("The file could not be read; upload it again") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise RecordError("A file can be at most 5 MB")
    if not raw.startswith(FILE_TYPES[content_type]):
        raise RecordError("The file content does not match its type")
    file_id = secrets.token_hex(12)
    clean_name = re.sub(r"[\x00-\x1f/\\]", "_", (name or "file").strip())[:120] or "file"
    meta = {"id": file_id, "name": clean_name, "type": content_type, "size": len(raw), "added_at": _now(), "added_by": user}
    docstore.write_text(_file_doc(file_id), json.dumps({"meta": meta, "data": base64.b64encode(raw).decode()}))
    return meta


def file_meta(file_id: str) -> Optional[Dict[str, Any]]:
    try:
        text = docstore.read_text(_file_doc(file_id))
    except NotFound:
        return None
    return json.loads(text)["meta"] if text else None


def read_file(file_id: str) -> Optional[Dict[str, Any]]:
    try:
        text = docstore.read_text(_file_doc(file_id))
    except NotFound:
        return None
    if not text:
        return None
    payload = json.loads(text)
    return {"meta": payload["meta"], "data": base64.b64decode(payload["data"])}


def delete_file(file_id: str) -> None:
    try:
        docstore.delete(_file_doc(file_id))
    except NotFound:
        pass


# --------------------------------------------------------------------------- #
# Who may see what
# --------------------------------------------------------------------------- #

def can_read(entity: Entity, role: str) -> bool:
    return role in entity.read


def can_write(entity: Entity, role: str, record: Optional[Dict[str, Any]], user_email: str) -> bool:
    if role in entity.write:
        return True
    if role in entity.own_write:
        return record is None or str(record.get("created_by") or "").lower() == user_email.lower()
    return False


def for_viewer(entity: Entity, record: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Hide private (money) fields from roles outside management and finance."""
    if role in ("admin", "manager", "finance"):
        return record
    private = {f.name for f in entity.fields if f.private}
    return {k: v for k, v in record.items() if k not in private} if private else record
