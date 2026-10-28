"""Approval flow of the ERP documents (blueprint A.1): the Konseptor drafts and submits, the
Pengulas reviews (corrects, returns or forwards) and the Pemutus approves (corrects, returns to the
reviewer or approves). Each step is kept in the record's history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import docstore, records
from .entities import ENTITIES, Entity
from .fields import ACTION_HOOKS

ACTIONS = ("submit", "review", "approve", "return", "reopen")


class WorkflowError(ValueError):
    pass


def _separation() -> bool:
    """Different people for each step unless company settings turn it off (very small teams)."""
    settings = records.get_singleton("settings") or {}
    return settings.get("approval_separation") is not False


def _last(history: List[Dict[str, Any]], step: str) -> str:
    for h in reversed(history):
        if h.get("action") == step:
            return str(h.get("by") or "").lower()
    return ""


def allowed(entity: Entity, record: Dict[str, Any], role: str, email: str) -> List[str]:
    """Actions this user may take on the record now."""
    if not entity.workflow:
        return []
    state = record.get("wf_status") or "draft"
    history = record.get("wf_history") or []
    me = email.lower()
    sep = _separation()
    out: List[str] = []
    if state in ("draft", "returned") and records.can_write(entity, role, record, email):
        out.append("submit")
    if state == "submitted" and role in entity.reviewers and not (sep and _last(history, "submit") == me):
        out += ["review", "return"]
    if state == "reviewed" and role in entity.approvers and not (sep and me in (_last(history, "submit"), _last(history, "review"))):
        out += ["approve", "return"]
    if state == "approved" and role in entity.approvers:
        out.append("reopen")
    return out


def act(entity_name: str, record_id: str, action: str, note: str, role: str, email: str) -> Dict[str, Any]:
    entity = ENTITIES[entity_name]
    if not entity.workflow:
        raise WorkflowError("This record has no approval flow")
    if action not in ACTIONS:
        raise WorkflowError("Unknown approval step")
    note = (note or "").strip()[:1000]
    with docstore.lock(records._lock_name(entity_name)):
        record = records.get_record(entity_name, record_id)
        if not records.can_see(entity, role, record, email):
            raise records.NotFound()
        if action not in allowed(entity, record, role, email):
            raise WorkflowError("You cannot take this step on this record now")
        if action in ("return", "reopen") and not note:
            raise WorkflowError("Write the reason in the note")
        state = record.get("wf_status") or "draft"
        new = {"submit": "submitted", "review": "reviewed", "approve": "approved", "reopen": "draft",
               "return": "returned" if state == "submitted" else "submitted"}[action]
        history = list(record.get("wf_history") or [])
        history.append({"action": action, "from": state, "to": new, "by": email, "role": role, "note": note,
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        record["wf_status"] = new
        record["wf_history"] = history[-200:]
        record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record["updated_by"] = email
        hook = ACTION_HOOKS.get(entity_name)
        if hook is not None:
            hook(record, action, email, role)
        import json
        docstore.write_text(records._doc(entity_name, record_id), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return record


def inbox(role: str, email: str) -> List[Dict[str, Any]]:
    """Records waiting for this user: to review, to approve, or returned to the drafter."""
    out: List[Dict[str, Any]] = []
    me = email.lower()
    for name, entity in ENTITIES.items():
        if not entity.workflow or not records.can_read(entity, role):
            continue
        for r in records.list_records(name):
            if not records.can_see(entity, role, r, email):
                continue
            state = r.get("wf_status") or "draft"
            acts = allowed(entity, r, role, email)
            mine = str(r.get("created_by") or "").lower() == me
            if (state in ("submitted", "reviewed") and acts) or (state == "returned" and mine):
                last: Optional[Dict[str, Any]] = (r.get("wf_history") or [None])[-1]
                out.append({"entity": name, "id": r["id"], "title": str(r.get(entity.title) or r["id"]),
                            "label_one": entity.label_one, "state": state, "since": (last or {}).get("at") or r.get("updated_at"),
                            "by": (last or {}).get("by") or r.get("updated_by"), "note": (last or {}).get("note") or ""})
    out.sort(key=lambda x: str(x.get("since") or ""))
    return out
