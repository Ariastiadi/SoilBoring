"""Worksheets (catalogue and calculation preview), the sample register, coordinate
conversion and Google Earth (KML) export."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import cpt_calc, details, geo, records, sheets, storage
from ..auth import get_current_user
from ..calcbase import CalcError
from ..entities import ENTITIES

router = APIRouter(prefix="/api", tags=["worksheets"])


@router.get("/worksheets")
def worksheet_catalog(user=Depends(get_current_user)):
    return sheets.catalog()


class CalcIn(BaseModel):
    kind: str = Field(pattern="^(field|lab|cpt)$")
    key: str = Field(default="", max_length=60)
    data: Dict[str, Any] = Field(default_factory=dict)


@router.post("/worksheets/calc")
def worksheet_calc(payload: CalcIn, user=Depends(get_current_user)):
    """Calculate a worksheet without saving it (preview in the form)."""
    try:
        if payload.kind == "cpt":
            entity = ENTITIES["cpt"]
            clean = records.clean(entity, payload.data, lambda *_: True)
            return cpt_calc.interpret(clean)
        entity = ENTITIES["field_activities" if payload.kind == "field" else "lab_tests"]
        variant_field = entity.field("data" if payload.kind == "field" else "raw")
        selector = "method" if payload.kind == "field" else "test_type"
        assert variant_field is not None
        clean = records._clean_value(variant_field, payload.data, variant_field.label, {selector: payload.key}, lambda *_: True)
        out = sheets.calculate(payload.kind, payload.key, clean or {})
    except (CalcError, records.RecordError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if out is None:
        raise HTTPException(status_code=422, detail="This worksheet has no calculation")
    return out


@router.get("/samples")
def sample_register(project: Optional[str] = Query(default=None, max_length=200), user=Depends(get_current_user)):
    """Every sample taken in the boreholes, with the laboratory tests asked for or done on it."""
    reports = {r["BoreholeID"]: r for r in storage.load_reports()}
    tests = records.list_records("lab_tests")
    out: List[Dict[str, Any]] = []
    for borehole_id, entry in details.all_details().items():
        report = reports.get(borehole_id)
        if report is None:
            continue
        if project and str(report.get("ProjectName") or "").strip().lower() != project.strip().lower():
            continue
        for s in entry["samples"]:
            ref = str(s.get("ref") or "").strip()
            mine = [t for t in tests if str(t.get("borehole_id") or "").lower() == borehole_id.lower()
                    and ((ref and str(t.get("sample_ref") or "").lower() == ref.lower())
                         or abs(float(t.get("depth_top") or -1) - float(s.get("top") or 0)) < 0.01)]
            out.append({
                "borehole_id": borehole_id, "project": report.get("ProjectName", ""),
                "top": s.get("top"), "base": s.get("base"), "type": s.get("type", ""), "ref": ref,
                "remarks": s.get("remarks", ""),
                "tests": [{"id": t["id"], "test_type": t.get("test_type"), "status": t.get("status")} for t in mine],
            })
    out.sort(key=lambda x: (x["borehole_id"], float(x["top"] or 0)))
    return out


class CoordRow(BaseModel):
    name: str = Field(default="", max_length=80)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    easting: Optional[float] = None
    northing: Optional[float] = None
    zone: Optional[int] = None
    hemisphere: str = Field(default="S", max_length=1)
    elevation: Optional[float] = None


class CoordIn(BaseModel):
    rows: List[CoordRow] = Field(max_length=5000)


@router.post("/tools/coordinates")
def convert_coordinates(payload: CoordIn, user=Depends(get_current_user)):
    """Latitude/longitude to UTM, or UTM to latitude/longitude, row by row."""
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(payload.rows, start=1):
        try:
            if row.latitude is not None and row.longitude is not None:
                lat, lon = row.latitude, row.longitude
            elif row.easting is not None and row.northing is not None and row.zone:
                found = geo.from_utm(row.easting, row.northing, row.zone, row.hemisphere or "S")
                lat, lon = found["latitude"], found["longitude"]
            else:
                out.append({"name": row.name, "error": "Enter latitude and longitude, or easting, northing and zone"})
                continue
            utm = geo.to_utm(lat, lon)
            item: Dict[str, Any] = {"name": row.name, "latitude": round(lat, 8), "longitude": round(lon, 8),
                                    "elevation": row.elevation, "dms": (geo.describe(lat, lon) or {}).get("dms", "")}
            item.update(utm)
            out.append(item)
        except ValueError as exc:
            out.append({"name": row.name, "error": f"Row {i}: {exc}"})
    return out


class KmlPoint(BaseModel):
    name: str = Field(default="", max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation: Optional[float] = None
    folder: str = Field(default="Points", max_length=60)
    description: str = Field(default="", max_length=500)


class KmlIn(BaseModel):
    name: str = Field(default="Points", max_length=120)
    points: List[KmlPoint] = Field(max_length=5000)


def _kml_response(name: str, text: str) -> Response:
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "points"
    return Response(content=text, media_type="application/vnd.google-earth.kml+xml", headers={
        "Content-Disposition": f'attachment; filename="{safe}.kml"', "Cache-Control": "no-store"})


@router.post("/tools/kml")
def points_kml(payload: KmlIn, user=Depends(get_current_user)):
    return _kml_response(payload.name, geo.kml(payload.name, [
        (p.name, p.latitude, p.longitude, p.elevation, p.folder, p.description) for p in payload.points]))


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("/export/kml")
def project_kml(project_id: str = Query(min_length=1, max_length=40), user=Depends(get_current_user)):
    """Boreholes, CPT and field points of one project for Google Earth."""
    try:
        project = records.get_record("projects", project_id)
    except records.NotFound as exc:
        raise HTTPException(status_code=404, detail="Not Found") from exc
    name = str(project.get("name") or "")
    points = []
    for r in storage.load_reports():
        if str(r.get("ProjectName") or "").strip().lower() != name.strip().lower():
            continue
        lat, lon = _f(r.get("Latitude")), _f(r.get("Longitude"))
        if lat is not None and lon is not None:
            points.append((r["BoreholeID"], lat, lon, _f(r.get("GroundElevation_mRL")), "Boreholes",
                           f"Depth {r.get('FinalDepth_m') or '-'} m"))
    for c in records.list_records("cpt"):
        if c.get("project_id") == project_id and c.get("latitude") is not None and c.get("longitude") is not None:
            points.append((str(c.get("test_id")), float(c["latitude"]), float(c["longitude"]), c.get("elevation"),
                           "CPT / sondir", f"Depth {c.get('final_depth') or '-'} m"))
    for a in records.list_records("field_activities"):
        if a.get("project_id") == project_id and a.get("latitude") is not None and a.get("longitude") is not None:
            points.append((str(a.get("code")), float(a["latitude"]), float(a["longitude"]), a.get("elevation"),
                           "Field work", str(a.get("method") or "")))
        if a.get("project_id") == project_id and a.get("method") == "coordinates":
            for row in (a.get("data") or {}).get("points") or []:
                lat, lon = _f(row.get("latitude")), _f(row.get("longitude"))
                if lat is not None and lon is not None:
                    points.append((str(row.get("point") or ""), lat, lon, _f(row.get("elevation")), "Field work",
                                   str(row.get("description") or "")))
    if not points:
        raise HTTPException(status_code=422, detail="No points with coordinates in this project")
    return _kml_response(name or "project", geo.kml(name or "Project", points))
