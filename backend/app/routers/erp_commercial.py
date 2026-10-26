"""Commercial ERP views and actions (blueprint A.1): pricing configuration, conversion of an
approved PBD into a quotation, weekly rows from a Gantt chart, client card, receivable aging and
NPAR, collection notes and the commercial overview for the management dashboard."""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import audit, erp_commercial as calc, records
from ..auth import get_current_user
from ..entities import ENTITIES, SERVICE_LINES

router = APIRouter(prefix="/api/erp/commercial", tags=["erp-commercial"])

_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _role(user: dict) -> str:
    return str(user.get("role", "general"))


def _need_read(user: dict, *entities: str) -> None:
    for name in entities:
        if not records.can_read(ENTITIES[name], _role(user)):
            raise HTTPException(status_code=403, detail="Your role cannot open this page")


def _settings() -> Optional[Dict[str, Any]]:
    return records.get_singleton("settings")


def _visible(entity: str, user: dict) -> List[Dict[str, Any]]:
    e = ENTITIES[entity]
    if not records.can_read(e, _role(user)):
        return []
    return [r for r in records.list_records(entity) if records.can_see(e, _role(user), r, user["email"])]


def _today(as_of: Optional[str]) -> str:
    if as_of:
        try:
            return date.fromisoformat(as_of).isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="as_of is not a valid date") from exc
    return date.today().isoformat()


@router.get("/config")
def pricing_config(user=Depends(get_current_user)):
    """Difficulty factors, risk premium table, zones, provinces and limits in force (company
    settings, or the company defaults while the settings leave them empty)."""
    _need_read(user, "pbd")
    return calc.config(_settings())


class QuoteRequest(BaseModel):
    date: Optional[str] = Field(default=None, pattern=_DATE)


@router.post("/pbd/{pbd_id}/quotation", status_code=201)
def pbd_to_quotation(pbd_id: str, payload: QuoteRequest, user=Depends(get_current_user)):
    """Conversion to client rates (A.1.5): a draft quotation from an approved PBD."""
    pbd_entity, quotes = ENTITIES["pbd"], ENTITIES["quotes"]
    role = _role(user)
    if not records.can_read(pbd_entity, role):
        raise HTTPException(status_code=404, detail="Not Found")
    if not records.can_write(quotes, role, None, user["email"]):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    try:
        pbd = records.get_record("pbd", pbd_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    if pbd.get("wf_status") != "approved":
        raise HTTPException(status_code=409, detail="Only an approved PBD can be converted into a quotation")
    rates = {r["id"]: r for r in records.list_records("rates")}
    project = records.get_record("projects", pbd["project_id"]) if pbd.get("project_id") else None
    client = None
    if project and project.get("client_id"):
        try:
            client = records.get_record("clients", project["client_id"])
        except records.NotFound:
            client = None
    try:
        data = calc.quotation_from_pbd(pbd, rates, client, payload.date or date.today().isoformat())
        quote = records.save("quotes", data, user["email"])
    except calc.CommercialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except records.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(user["email"], "quotes.created", str(quote.get("number")), {"from": pbd.get("number")})
    return {**records.for_viewer(quotes, quote, role), "_can_edit": True}


class GanttRequest(BaseModel):
    activities: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    budget: Optional[float] = Field(default=None, ge=0, le=1e14)


@router.post("/work-plans/weeks")
def weeks_from_gantt(payload: GanttRequest, user=Depends(get_current_user)):
    """Weekly rows (planned progress and budget) spread from the Gantt chart; not saved."""
    _need_read(user, "work_plans")
    try:
        return calc.weeks_from_gantt(payload.activities, payload.budget)
    except calc.CommercialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="The activities are not valid") from exc


@router.get("/clients/{client_id}/card")
def client_card(client_id: str, as_of: Optional[str] = Query(default=None, pattern=_DATE), user=Depends(get_current_user)):
    """Client card (A.1.11): statistics, payment behaviour, aging and pipeline of one client."""
    _need_read(user, "clients", "invoices")
    try:
        client = records.get_record("clients", client_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    return calc.client_card(client, _visible("projects", user), _visible("contracts", user), _visible("invoices", user),
                            _visible("work_plans", user), _visible("pbd", user), _visible("quotes", user),
                            _visible("client_decisions", user), _visible("clients", user), _settings(), _today(as_of))


@router.get("/clients")
def client_summaries(as_of: Optional[str] = Query(default=None, pattern=_DATE), user=Depends(get_current_user)):
    """Client recap (Rekapitulasi Klien): one line per client."""
    _need_read(user, "clients", "invoices")
    today = _today(as_of)
    projects, contracts, invoices = _visible("projects", user), _visible("contracts", user), _visible("invoices", user)
    plans, clients = _visible("work_plans", user), _visible("clients", user)
    out = []
    for c in clients:
        card = calc.client_card(c, projects, contracts, invoices, plans, [], [], [], clients, _settings(), today)
        s = card["stats"]
        out.append({"id": c["id"], "name": c.get("name"), "type": c.get("type"), "since_year": card["client"]["since_year"],
                    "projects": s["projects"], "contract_value": s["contract_value"], "invoiced": s["invoiced"], "paid": s["paid"],
                    "outstanding": s["outstanding"], "overdue": s["overdue"], "npar": s["npar"],
                    "avg_days_to_pay": s["avg_days_to_pay"], "on_time_rate_pct": s["on_time_rate_pct"], "rating": s["rating"]})
    out.sort(key=lambda r: (-(r["contract_value"] or 0), str(r["name"] or "")))
    return out


@router.get("/receivables")
def receivables(as_of: Optional[str] = Query(default=None, pattern=_DATE), client_id: Optional[str] = Query(default=None, max_length=40),
                user=Depends(get_current_user)):
    """Receivable aging (A.1.10) and the NPAR list."""
    _need_read(user, "invoices")
    return calc.receivables(_visible("invoices", user), _visible("projects", user), _visible("clients", user), _settings(),
                            _today(as_of), client_id)


class CollectionNote(BaseModel):
    date: Optional[str] = Field(default=None, pattern=_DATE)
    action: str = Field(min_length=2, max_length=20)
    note: str = Field(min_length=1, max_length=500)
    next_date: Optional[str] = Field(default=None, pattern=_DATE)


@router.post("/invoices/{invoice_id}/collection-notes")
def add_collection_note(invoice_id: str, payload: CollectionNote, user=Depends(get_current_user)):
    """Commercial staff and finance add a collection note without editing the invoice itself."""
    entity = ENTITIES["invoices"]
    if _role(user) not in ("admin", "manager", "finance"):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    for _attempt in range(3):
        try:
            invoice = records.get_record("invoices", invoice_id)
        except records.NotFound:
            raise HTTPException(status_code=404, detail="Not Found")
        notes = list(invoice.get("collection_notes") or [])
        notes.append({"date": payload.date or date.today().isoformat(), "action": payload.action, "note": payload.note,
                      "next_date": payload.next_date or "", "by": user["email"]})
        data = {k: v for k, v in invoice.items() if not k.startswith("_")}
        data["collection_notes"] = notes
        try:
            saved = records.save("invoices", data, user["email"], record_id=invoice_id, expected_updated_at=invoice.get("updated_at"))
        except records.RecordError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except records.ConflictError:
            continue  # changed in between: read again
        audit.record(user["email"], "invoices.collection_note", str(saved.get("number") or invoice_id), {"action": payload.action})
        return {**records.for_viewer(entity, saved, _role(user)), "_can_edit": records.can_write(entity, _role(user), saved, user["email"])}
    raise HTTPException(status_code=409, detail="The invoice is being changed; try again")


@router.get("/overview")
def commercial_overview(as_of: Optional[str] = Query(default=None, pattern=_DATE), user=Depends(get_current_user)):
    """Commercial figures for the management dashboard (A.1.14)."""
    _need_read(user, "invoices", "pbd")
    names = ("projects", "clients", "contracts", "invoices", "pbd", "client_decisions", "quotes", "work_plans", "guarantees")
    data = {n: _visible(n, user) for n in names}
    return calc.overview(data, _settings(), dict(SERVICE_LINES), _today(as_of))
