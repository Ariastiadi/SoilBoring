"""Client reports: templates, the report content for the print, the public seal check
(``/api/verify/...``, no sign-in) and the client portal (``/api/client/...``, client accounts)."""
from fastapi import APIRouter, Depends, HTTPException

from .. import client_reports, records, report_templates, seals
from ..auth import get_current_user
from ..entities import ENTITIES

router = APIRouter(prefix="/api", tags=["client-reports"])


def _staff_report(report_id: str, user: dict) -> dict:
    entity = ENTITIES["project_reports"]
    role = user.get("role", "general")
    if not records.can_read(entity, role):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")
    try:
        report = records.get_record("project_reports", report_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="Not Found")
    if not records.can_see(entity, role, report, user["email"]):
        raise HTTPException(status_code=404, detail="Not Found")
    return report


@router.get("/client-reports/templates")
def templates(user=Depends(get_current_user)):
    """Section outline of each project type, and the annex kinds."""
    if not records.can_read(ENTITIES["project_reports"], user.get("role", "general")):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")
    return {
        "templates": [{"key": key, "label": label, "sections": report_templates.outline(key)}
                      for key, (label, _) in report_templates.TEMPLATES.items()],
        "annex_kinds": report_templates.ANNEX_KINDS,
    }


@router.get("/client-reports/{report_id}/content")
def report_content(report_id: str, user=Depends(get_current_user)):
    """What the report prints: frozen at issue for an approved report, live data otherwise."""
    return client_reports.report_view(_staff_report(report_id, user))


@router.get("/client-reports/{report_id}/annex-candidates")
def annex_candidates(report_id: str, user=Depends(get_current_user)):
    """Records and files of the report's project that can be listed as annexes."""
    report = _staff_report(report_id, user)
    return _candidates(report.get("project_id") or "", report)


@router.get("/client-reports/annex-candidates/{project_id}")
def annex_candidates_for_project(project_id: str, user=Depends(get_current_user)):
    if not records.can_read(ENTITIES["project_reports"], user.get("role", "general")):
        raise HTTPException(status_code=403, detail="Your role cannot open this page")
    return _candidates(project_id, {})


def _candidates(project_id: str, report: dict) -> list:
    try:
        project = records.get_record("projects", project_id)
    except records.NotFound:
        return []
    data = client_reports.project_data(project)
    out = []

    def add(kind: str, name: str, ref: str, detail: str = "") -> None:
        out.append({"kind": kind, "name": name, "detail": detail, "ref": ref})

    for b in data["boreholes"]:
        add("borehole_log", b["id"], b["id"])
    for b in data["boreholes"]:
        if b["photos"]:
            add("photos", f"{b['id']} ({b['photos']})", b["id"])
    for c in data["cpt"]:
        add("cpt_plot", c["test_id"], c["id"])
    for f in data["field"]:
        add("field_sheet", f["code"], f["id"], f["method_label"])
    for x in data["lab"]:
        add("lab_sheet", f"{x['borehole_id']} {x['sample_ref']}", x["id"], x["test_label"])
    # Calibration certificates of the equipment used in the project's laboratory tests.
    lab_ids = {x["id"] for x in data["lab"]}
    used = {row.get("equipment_id") for t in records.list_records("lab_tests") if t.get("id") in lab_ids
            for row in t.get("equipment_used") or []}
    for eq in records.list_records("equipment"):
        if eq.get("id") in used:
            add("calibration", " ".join(str(x) for x in (eq.get("code"), eq.get("name"), eq.get("calibration_cert")) if x), eq["id"])
    for f in report.get("files") or []:
        add("photos" if str(f.get("type", "")).startswith("image/") else "other", f.get("name", ""), f.get("id", ""))
    for f in project.get("files") or []:
        add("other", f.get("name", ""), f.get("id", ""))
    return out


# --------------------------------------------------------------------------- #
# Public seal check (no sign-in)
# --------------------------------------------------------------------------- #

@router.get("/verify/{token}")
def verify(token: str):
    """Kind, number and title, project, issuer, date and status of a sealed document; nothing else."""
    if len(token) > 80:
        raise HTTPException(status_code=404, detail="No document with this code")
    seal = seals.lookup(token)
    if seal is None:
        raise HTTPException(status_code=404, detail="No document with this code")
    return seals.public_view(seal)


# --------------------------------------------------------------------------- #
# Client portal: client accounts only, their own projects only
# --------------------------------------------------------------------------- #

def _client(user: dict) -> list:
    if user.get("role") != "client":
        raise HTTPException(status_code=403, detail="Only client accounts use the client portal")
    return list(user.get("client_ids") or [])


@router.get("/client/overview")
def client_overview(user=Depends(get_current_user)):
    return client_reports.client_overview(_client(user))


@router.get("/client/reports/{report_id}")
def client_report(report_id: str, user=Depends(get_current_user)):
    found = client_reports.client_report(_client(user), report_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return found


@router.get("/client/boreholes/{borehole_id:path}")
def client_borehole(borehole_id: str, user=Depends(get_current_user)):
    found = client_reports.client_borehole(_client(user), borehole_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return found


@router.get("/client/projects/{project_id}/lab")
def client_lab(project_id: str, user=Depends(get_current_user)):
    found = client_reports.client_lab(_client(user), project_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return found
