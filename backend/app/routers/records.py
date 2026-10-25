"""Business records: clients, projects, quotations, contracts, field work, laboratory,
analyses, reports, invoices and company settings (see entities.py)."""
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import audit, records
from ..auth import get_current_user
from ..entities import ENTITIES, Entity, public_schema

router = APIRouter(prefix="/api", tags=["records"])


def _entity(name: str) -> Entity:
    entity = ENTITIES.get(name)
    if entity is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return entity


def _readable(entity: Entity, user: dict) -> None:
    if not records.can_read(entity, user.get("role", "general")):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")


def _changes(entity: Entity, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for f in entity.fields:
        if f.type in ("items", "json", "files"):
            if before.get(f.name) != after.get(f.name):
                out[f.name] = "changed"
        elif (before.get(f.name) or "") != (after.get(f.name) or ""):
            out[f.name] = [before.get(f.name), after.get(f.name)]
    return out


@router.get("/schemas")
def schemas(user=Depends(get_current_user)):
    role = user.get("role", "general")
    out = public_schema()
    for name, entity in ENTITIES.items():
        out[name]["can_read"] = records.can_read(entity, role)
        out[name]["can_create"] = records.can_write(entity, role, None, user["email"])
    return out


@router.get("/records/{entity_name}")
def list_records(entity_name: str, project_id: Optional[str] = Query(default=None, max_length=40), user=Depends(get_current_user)):
    entity = _entity(entity_name)
    _readable(entity, user)
    role = user.get("role", "general")
    items = records.list_records(entity_name)
    if project_id:
        items = [r for r in items if r.get("project_id") == project_id]
    key = entity.sort.lstrip("-")
    items.sort(key=lambda r: str(r.get(key) or ""), reverse=entity.sort.startswith("-"))
    return [
        {**records.for_viewer(entity, r, role), "_can_edit": records.can_write(entity, role, r, user["email"])}
        for r in items
    ]


@router.get("/records/{entity_name}/{record_id}")
def get_record(entity_name: str, record_id: str, user=Depends(get_current_user)):
    entity = _entity(entity_name)
    _readable(entity, user)
    try:
        record = records.get_record(entity_name, record_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    role = user.get("role", "general")
    return {**records.for_viewer(entity, record, role), "_can_edit": records.can_write(entity, role, record, user["email"])}


def _store(entity: Entity, user: dict, data: Dict[str, Any], record_id: Optional[str]):
    role = user.get("role", "general")
    existing = None
    if record_id is not None:
        try:
            existing = records.get_record(entity.name, record_id)
        except records.NotFound:
            raise HTTPException(status_code=404, detail="Not Found")
    elif entity.singleton:
        existing = records.get_singleton(entity.name)
    if not records.can_write(entity, role, existing, user["email"]):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    if existing is not None and role not in ("admin", "manager", "finance"):
        # Private (money) fields the viewer never saw are kept as they are.
        for f in entity.fields:
            if f.private:
                data[f.name] = existing.get(f.name)
    expected = data.pop("expected_updated_at", None)
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    if entity.name == "analyses":
        from .. import analysis_runner

        try:
            data["_results"] = analysis_runner.run(str(data.get("type") or ""), data.get("inputs") or {})
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    results = data.pop("_results", None)
    try:
        record = records.save(entity.name, data, user["email"], record_id=existing["id"] if existing else None,
                              expected_updated_at=expected if existing else None)
        if results is not None:
            record = records.attach_results(entity.name, record["id"], results)
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except records.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    action = "record.updated" if existing else "record.created"
    audit.record(user["email"], f"{entity.name}.{action.split('.')[1]}", str(record.get(entity.title) or record["id"]),
                 _changes(entity, existing or {}, record))
    return {**records.for_viewer(entity, record, role), "_can_edit": True}


@router.post("/records/{entity_name}", status_code=201)
def create_record(entity_name: str, data: Dict[str, Any] = Body(...), user=Depends(get_current_user)):
    return _store(_entity(entity_name), user, dict(data), None)


@router.put("/records/{entity_name}/{record_id}")
def update_record(entity_name: str, record_id: str, data: Dict[str, Any] = Body(...), user=Depends(get_current_user)):
    return _store(_entity(entity_name), user, dict(data), record_id)


@router.delete("/records/{entity_name}/{record_id}")
def delete_record(entity_name: str, record_id: str, user=Depends(get_current_user)):
    entity = _entity(entity_name)
    try:
        existing = records.get_record(entity_name, record_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    if not records.can_write(entity, user.get("role", "general"), existing, user["email"]):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    try:
        removed = records.remove(entity_name, record_id)
    except records.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(user["email"], f"{entity_name}.deleted", str(removed.get(entity.title) or record_id))
    return {"status": "deleted"}


class AnalysisRun(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    inputs: Dict[str, Any] = Field(default_factory=dict)


@router.post("/analyses/run")
def run_analysis(payload: AnalysisRun, user=Depends(get_current_user)):
    """Calculate without saving (preview in the analysis form)."""
    from .. import analysis_runner

    try:
        return analysis_runner.run(payload.type, payload.inputs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class FileUpload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=3, max_length=120)
    data_base64: str = Field(min_length=4, max_length=records.MAX_FILE_BYTES * 4 // 3 + 16)


@router.post("/files", status_code=201)
def upload_file(payload: FileUpload, user=Depends(get_current_user)):
    if user.get("role") not in ("admin", "manager", "general", "lab", "finance"):
        raise HTTPException(status_code=403, detail="Your role cannot change this record")
    try:
        return records.add_file(payload.name, payload.content_type, payload.data_base64, user["email"])
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/files/{file_id}")
def download_file(file_id: str, user=Depends(get_current_user)):
    found = records.read_file(file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not Found")
    meta = found["meta"]
    ascii_name = meta["name"].encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    return Response(content=found["data"], media_type=meta["type"], headers={
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(meta["name"])}',
    })
