"""Client reports (``project_reports``): the template outline, versions, the report content
assembled from the project's data, issue with an integrity seal on approval, the seal of
authorised laboratory results, and what a client account may see of its own projects.

The content of a report (the "bundle") is assembled here on the server, so the print, the
client portal and the seal all use the same data: at approval it is frozen into the seal
(see seals.py) and the client sees exactly what was issued.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from . import details, report_templates, seals, storage

REPORT_TYPE = "Soil investigation report"
LAB_TYPE = "Laboratory test result"
UNDISTURBED = {"U", "UT", "TW"}


def _records():
    from . import records

    return records


def _num(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _same(a: Any, b: Any) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def _get(entity: str, record_id: str) -> Dict[str, Any]:
    records = _records()
    try:
        return records.get_record(entity, record_id) if record_id else {}
    except records.NotFound:
        return {}


def _label(options: Any, value: Any) -> str:
    for option in options or []:
        if option[0] == value:
            return str(option[1])
    return str(value or "")


def gw_encountered(row: Dict[str, Any]) -> bool:
    return str(row.get("GroundwaterEncountered") or "").strip().lower() in ("true", "yes", "1")


# --------------------------------------------------------------------------- #
# The project's data
# --------------------------------------------------------------------------- #

def project_logs(project: Dict[str, Any], rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Borehole logs whose Project is the project's name."""
    if not project.get("name"):
        return []
    rows = storage.load_reports() if rows is None else rows
    return [r for r in rows if _same(r.get("ProjectName"), project.get("name"))]


def borehole_data(row: Dict[str, Any], det: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    det = det or {}
    gw = gw_encountered(row)
    return {
        "id": row.get("BoreholeID", ""), "site": row.get("SiteName", ""), "start": row.get("StartDate", ""),
        "end": row.get("EndDate", ""), "method": row.get("DrillingMethod", ""), "final_depth": _num(row.get("FinalDepth_m")),
        "gw_encountered": gw, "gw_depth": _num(row.get("GroundwaterDepth_m")) if gw else None,
        "latitude": _num(row.get("Latitude")), "longitude": _num(row.get("Longitude")),
        "elevation": _num(row.get("GroundElevation_mRL")), "uscs": row.get("USCS_Class", ""),
        "avg_n": _num(row.get("Avg_SPT_N60")), "description": row.get("SoilDescription", ""),
        "layers": [{"top": x.get("top"), "base": x.get("base"), "uscs": x.get("uscs", ""), "description": x.get("description", "")}
                   for x in det.get("layers") or []],
        "spt": [{"depth": x.get("depth"), "n": x.get("n"), "reported": x.get("reported", ""),
                 "refusal": "/" in str(x.get("reported", ""))} for x in det.get("spt") or []],
        "samples": [{"top": x.get("top"), "base": x.get("base"), "type": x.get("type", ""), "ref": x.get("ref", "")}
                    for x in det.get("samples") or []],
        "core_runs": len(det.get("core") or []),
        "photos": len(det.get("photos") or []),
    }


def lab_values(test: Dict[str, Any]) -> List[Dict[str, Any]]:
    from .entities import LAB_RESULTS

    results = test.get("results") or {}
    out = []
    for f in LAB_RESULTS.get(str(test.get("test_type") or ""), []):
        value = results.get(f.name)
        if value not in (None, "", [], {}):
            out.append({"key": f.name, "label": f.label, "value": value})
    return out


def lab_item(test: Dict[str, Any]) -> Dict[str, Any]:
    from .entities import LAB_TESTS

    return {
        "id": test.get("id", ""), "borehole_id": test.get("borehole_id", ""), "sample_ref": test.get("sample_ref", ""),
        "depth_top": test.get("depth_top"), "depth_base": test.get("depth_base"), "test_type": test.get("test_type", ""),
        "test_label": _label(LAB_TESTS, test.get("test_type")), "standard": test.get("standard", ""),
        "tested": test.get("tested", ""), "values": lab_values(test), "summary": test.get("summary", ""),
        "authorised": bool(test.get("authorised")), "authorised_at": test.get("authorised_at", ""),
        "seal_code": seals.format_code(test.get("seal_code") or "") if test.get("seal_code") else "",
        "disclaimer": test.get("report_disclaimer", ""),
    }


def project_lab(project: Dict[str, Any], borehole_ids: List[str]) -> List[Dict[str, Any]]:
    ids = {b.lower() for b in borehole_ids}
    tests = [t for t in _records().list_records("lab_tests")
             if t.get("status") == "done" and (t.get("project_id") == project.get("id") or str(t.get("borehole_id") or "").lower() in ids)]
    tests.sort(key=lambda t: (str(t.get("borehole_id")), _num(t.get("depth_top")) or 0, str(t.get("test_type"))))
    return [lab_item(t) for t in tests]


def _spt_stats(boreholes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[float]] = defaultdict(list)
    refusals: Counter = Counter()
    for bh in boreholes:
        layers = bh["layers"]
        for test in bh["spt"]:
            depth = _num(test.get("depth"))
            if depth is None:
                continue
            layer = next((x for x in layers if x["top"] <= depth < x["base"]), None) \
                or next((x for x in layers if x["top"] <= depth <= x["base"]), None)
            group = (layer or {}).get("uscs") or "–"
            if test.get("refusal"):
                refusals[group] += 1
            elif _num(test.get("n")) is not None:
                groups[group].append(float(test["n"]))
    out = []
    for group in sorted(set(groups) | set(refusals)):
        values = groups.get(group, [])
        out.append({"uscs": group, "count": len(values), "refusals": refusals.get(group, 0),
                    "min": min(values) if values else None, "max": max(values) if values else None,
                    "mean": round(sum(values) / len(values), 1) if values else None})
    return out


def _lab_stats(lab: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    found: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    labels: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for item in lab:
        for v in item["values"]:
            number = _num(v["value"]) if not isinstance(v["value"], bool) else None
            if number is None:
                continue
            key = (item["test_type"], v["key"])
            found[key].append(number)
            labels[key] = (item["test_label"], v["label"])
    out = []
    for key, values in found.items():
        test_label, label = labels[key]
        out.append({"test": test_label, "label": label, "count": len(values), "min": min(values), "max": max(values),
                    "mean": round(sum(values) / len(values), 3)})
    out.sort(key=lambda r: (r["test"], r["label"]))
    return out


def project_data(project: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the report sections draw on, for one project."""
    from .entities import ENTITIES, FIELD_METHODS

    records = _records()
    logs = sorted(project_logs(project), key=lambda r: str(r.get("BoreholeID")))
    all_det = details.all_details()
    boreholes = [borehole_data(r, all_det.get(r.get("BoreholeID", ""))) for r in logs]
    pid = project.get("id") or "-"
    cpt = []
    for c in sorted((x for x in records.list_records("cpt") if x.get("project_id") == pid), key=lambda x: str(x.get("test_id"))):
        readings = [r for r in c.get("readings") or [] if _num(r.get("qc")) is not None]
        cpt.append({"id": c["id"], "test_id": c.get("test_id", ""), "date": c.get("date", ""), "final_depth": c.get("final_depth"),
                    "gw_depth": c.get("gw_depth"), "max_qc": max((float(r["qc"]) for r in readings), default=None),
                    "unit": "kg/cm²" if (c.get("qc_unit") or "kgcm2") == "kgcm2" else "MPa", "readings": len(readings),
                    "summary": c.get("summary", "")})
    labels = {key: label for key, label, _ in FIELD_METHODS}
    field = [{"id": a["id"], "code": a.get("code", ""), "method": a.get("method", ""), "method_label": labels.get(a.get("method", ""), a.get("method", "")),
              "date": a.get("date", ""), "borehole_id": a.get("borehole_id", ""), "summary": a.get("summary", ""),
              "results": a.get("results", ""), "calc": a.get("results_calc") or {}}
             for a in sorted((x for x in records.list_records("field_activities") if x.get("project_id") == pid),
                             key=lambda x: (str(x.get("date")), str(x.get("code"))))]
    lab = project_lab(project, [b["id"] for b in boreholes])
    type_field = ENTITIES["analyses"].field("type")
    analyses = [{"id": a["id"], "title": a.get("title", ""), "type": a.get("type", ""),
                 "type_label": _label(type_field.options if type_field else [], a.get("type")),
                 "borehole_id": a.get("borehole_id", ""), "summary": a.get("summary", ""), "results": a.get("results") or {}}
                for a in sorted((x for x in records.list_records("analyses") if x.get("project_id") == pid),
                                key=lambda x: (str(x.get("type")), str(x.get("title"))))]
    samples = [s for b in boreholes for s in b["samples"]]
    scope = {
        "boreholes": len(boreholes), "metres": round(sum(b["final_depth"] or 0 for b in boreholes), 2),
        "spt": sum(len(b["spt"]) for b in boreholes), "samples": len(samples),
        "undisturbed": sum(1 for s in samples if str(s["type"]).upper() in UNDISTURBED),
        "core_runs": sum(b["core_runs"] for b in boreholes),
        "cpt": len(cpt), "cpt_metres": round(sum(_num(c["final_depth"]) or 0 for c in cpt), 2),
        "field": sorted(Counter(f["method_label"] for f in field).items()),
        "lab": sorted(Counter(x["test_label"] for x in lab).items()),
        "analyses": len(analyses),
    }
    return {"boreholes": boreholes, "cpt": cpt, "field": field, "lab": lab, "analyses": analyses, "scope": scope,
            "parameters": {"spt": _spt_stats(boreholes), "lab": _lab_stats(lab)}}


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #

def _legacy_sections(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reports written before the templates: the old layout as sections."""
    rows = [("summary", "Summary", "text", report.get("summary")), ("scope", "Scope of work", "scope", report.get("scope")),
            ("field", "Field investigation", "field", ""), ("cpt", "CPT / sondir", "cpt", ""),
            ("lab", "Laboratory results", "lab", ""), ("analyses", "Engineering analyses", "analyses:*", ""),
            ("recommendations", "Recommendations", "text", report.get("recommendations"))]
    return [{"key": k, "title": t, "source": s, "include": True, "text": str(x or "")} for k, t, s, x in rows]


def company() -> Dict[str, Any]:
    from . import config

    s = _records().get_singleton("settings") or {}
    return {"name": s.get("company_name") or config.ORG_NAME or "", "address": s.get("address", ""), "phone": s.get("phone", ""),
            "email": s.get("email", ""), "npwp": s.get("npwp", ""), "footer": s.get("report_footer", "")}


def build(report: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The report's content (as issued) and warnings for the staff preview."""
    project = _get("projects", report.get("project_id") or "")
    client = _get("clients", project.get("client_id") or "")
    data = project_data(project) if project else project_data({})
    catalog = dict(report_templates.reference_catalog())
    sections = [s for s in (report.get("sections") or []) if s.get("include") is not False] if report.get("sections") \
        else [s for s in _legacy_sections(report) if s["text"] or s["source"] != "text"]
    template = report.get("template") or ""
    content = {
        "document": {
            "type": REPORT_TYPE, "number": report.get("number", ""), "version": int(report.get("version") or 1),
            "title": report.get("title", ""), "date": report.get("date", ""), "template": template,
            "template_label": report_templates.TEMPLATES[template][0] if template in report_templates.TEMPLATES else "",
            "revision_note": report.get("revision_note", ""),
            "prepared_by": report.get("prepared_by", ""), "reviewed_by": report.get("reviewed_by", ""),
            "approved_by": report.get("approved_by", ""),
            "sections": [{"key": s.get("key", ""), "title": s.get("title", ""), "source": s.get("source") or "text",
                          "text": s.get("text", "")} for s in sections],
            "annexes": [{"kind": a.get("kind", ""), "title": a.get("title", ""), "ref": a.get("ref", "")} for a in report.get("annexes") or []],
            "references": [{"code": c, "title": catalog.get(c, "")} for c in report.get("references") or []],
            "other_references": report.get("other_references", ""),
        },
        "company": company(),
        "project": {"name": project.get("name", ""), "code": project.get("code", ""), "location": project.get("location", ""),
                    "province": project.get("province", ""),
                    "client": {"name": client.get("name", ""), "address": client.get("address", ""),
                               "contact_person": client.get("contact_person", "")}},
        "data": data,
    }
    warnings: List[Dict[str, Any]] = []
    if not project:
        warnings.append({"text": "The project of this report was not found"})
    pending = sum(1 for x in data["lab"] if not x["authorised"])
    if pending:
        warnings.append({"text": "{n} laboratory results are not authorised yet; they are marked in the report", "vars": {"n": pending}})
    for s in content["document"]["sections"]:
        if s["source"] == "text" and not str(s["text"]).strip():
            warnings.append({"text": "Section \"{title}\" has no text yet", "vars": {"title": s["title"]}})
    if not data["boreholes"] and not data["cpt"]:
        warnings.append({"text": "No boreholes or CPT are linked to the project yet"})
    return content, warnings


def compute_report(record: Dict[str, Any]) -> None:
    """COMPUTE_HOOK of project_reports: outline from the template, version, number, status."""
    records = _records()
    state = record.get("wf_status") or "draft"
    if record.get("status") != "superseded":
        record["status"] = {"submitted": "review", "reviewed": "review", "approved": "approved"}.get(state, "draft")
    template = record.get("template") or ""
    if template and not record.get("sections"):
        rows = report_templates.outline(template)
        legacy = {"summary": record.get("summary"), "scope": record.get("scope"), "recommendations": record.get("recommendations"),
                  "foundation": record.get("recommendations")}
        for row in rows:
            if legacy.get(str(row["key"])) and not row["text"]:
                row["text"] = legacy[str(row["key"])]
        record["sections"] = rows
    for row in record.get("sections") or []:
        row["source"] = row.get("source") or "text"
        if not report_templates.valid_source(row["source"]):
            raise records.RecordError("A section has an unknown content source")
        if row.get("include") is None:
            row["include"] = True
    family = record["id"]
    version = 1
    previous = record.get("supersedes_id") or ""
    if previous:
        prev = _get("project_reports", previous)
        if not prev or prev.get("id") == record["id"]:
            raise records.RecordError("The earlier version of this report was not found")
        if prev.get("wf_status") != "approved":
            raise records.RecordError("Only an approved report can be replaced by a new version")
        family = prev.get("family_id") or prev["id"]
        siblings = [r for r in records.list_records("project_reports") if (r.get("family_id") or r.get("id")) == family and r.get("id") != record["id"]]
        open_one = next((r for r in siblings if r.get("wf_status") != "approved"), None)
        if open_one:
            raise records.ConflictError("A newer version of this report is still open; finish it first")
        newer = [r for r in siblings if int(r.get("version") or 1) > int(prev.get("version") or 1)]
        if newer:
            raise records.RecordError("Choose the latest version of the report to revise")
        version = max(int(r.get("version") or 1) for r in siblings) + 1
        record["number"] = prev.get("number", record.get("number"))
        record["project_id"] = prev.get("project_id", record.get("project_id"))
        if not str(record.get("revision_note") or "").strip():
            raise records.RecordError("Write the revision note: what changed in this version")
    record["family_id"] = family
    record["version"] = version
    wanted = str(record.get("number") or "").strip().lower()
    for other in records.list_records("project_reports"):
        if other.get("id") != record["id"] and (other.get("family_id") or other.get("id")) != family \
                and str(other.get("number") or "").strip().lower() == wanted:
            raise records.ConflictError(f"Report number '{record.get('number')}' is already used")


def on_workflow(record: Dict[str, Any], action: str, email: str, role: str) -> None:
    """ACTION_HOOK of project_reports: signatories from the flow, issue and seal on approval."""
    from .workflow import WorkflowError

    state = record.get("wf_status") or "draft"
    if action == "reopen" and record.get("status") == "superseded":
        raise WorkflowError("A newer version replaces this report; make a new version instead of reopening it")
    if action == "submit" and not record.get("prepared_by"):
        record["prepared_by"] = email
    if action == "review":
        record["reviewed_by"] = email
    if action == "approve":
        record["approved_by"] = email
    record["status"] = {"submitted": "review", "reviewed": "review", "approved": "approved"}.get(state, "draft")
    family = record.get("family_id") or record["id"]
    if action == "reopen":
        seals.revoke("project_reports", family)
        return
    if action != "approve":
        return
    content, _ = build(record)
    seal = seals.issue(REPORT_TYPE, "project_reports", record["id"], family, {
        "number": f"{record.get('number', '')} v{int(record.get('version') or 1)}", "title": record.get("title", ""),
        "project": content["project"]["name"], "issuer": content["company"]["name"]}, email, content)
    record["seal_hash"] = seal["hash"]
    record["seal_code"] = seal["code"]
    record["sealed_at"] = seal["issued_at"]
    # The version this one replaces is marked superseded.
    records = _records()
    for other in records.list_records("project_reports"):
        if other.get("id") != record["id"] and (other.get("family_id") or other.get("id")) == family \
                and other.get("wf_status") == "approved" and other.get("status") != "superseded":
            other["status"] = "superseded"
            other["superseded_by"] = record["id"]
            import json

            from . import docstore

            docstore.write_text(records._doc("project_reports", other["id"]), json.dumps(other, ensure_ascii=False, separators=(",", ":")))


def report_view(report: Dict[str, Any]) -> Dict[str, Any]:
    """For staff: the content (frozen when issued), the seal, and whether the live data still matches."""
    seal = seals.lookup(report.get("seal_hash") or "") if report.get("seal_hash") else None
    content, warnings = build(report)
    if seal and report.get("wf_status") == "approved":
        issued = seal["sealed"]
        live = dict(issued)
        live["content"] = content
        return {"content": issued["content"], "warnings": [], "seal": seals.summary(seal),
                "changed_since_issue": seals.digest(seals.finite(live)) != seal["hash"]}
    return {"content": content, "warnings": warnings, "seal": seals.summary(seal), "changed_since_issue": False}


# --------------------------------------------------------------------------- #
# Laboratory results: sealed when authorised
# --------------------------------------------------------------------------- #

def _lab_project_name(test: Dict[str, Any]) -> str:
    project = _get("projects", test.get("project_id") or "")
    if project:
        return str(project.get("name") or "")
    row = storage.get_report(str(test.get("borehole_id") or "")) if test.get("borehole_id") else None
    return str((row or {}).get("ProjectName") or "")


def seal_lab_test(record: Dict[str, Any]) -> None:
    """After the lab test's own checks (erp_lab.compute_lab_test): seal newly authorised results,
    withdraw the seal when the authorisation is withdrawn."""
    previous = _get("lab_tests", record.get("id") or "")
    now, was = bool(record.get("authorised")), bool(previous.get("authorised"))
    if now and not was:
        item = lab_item(record)
        item.pop("seal_code", None)
        content = {"test": item, "raw": record.get("raw") or {}, "calc_summary": record.get("summary", ""),
                   "technician": record.get("technician", ""), "received": record.get("received", ""),
                   "uncertainty": record.get("uncertainty", ""), "authorised_by": record.get("authorised_by", "")}
        project = _lab_project_name(record)
        seal = seals.issue(LAB_TYPE, "lab_tests", record["id"], record["id"], {
            "number": f"{record.get('borehole_id', '')} / {record.get('sample_ref', '')}", "title": item["test_label"],
            "project": project, "issuer": company()["name"]}, str(record.get("authorised_by") or record.get("updated_by") or ""), content)
        record["seal_hash"] = seal["hash"]
        record["seal_code"] = seal["code"]
        record["sealed_at"] = seal["issued_at"]
    elif was and not now and record.get("id"):
        seals.revoke("lab_tests", record["id"])


# --------------------------------------------------------------------------- #
# Client accounts: their own projects only
# --------------------------------------------------------------------------- #

def client_projects(client_ids: List[str]) -> List[Dict[str, Any]]:
    wanted = set(client_ids or [])
    if not wanted:
        return []
    return sorted((p for p in _records().list_records("projects") if p.get("client_id") in wanted),
                  key=lambda p: str(p.get("start_date") or ""), reverse=True)


def issued_reports(project_id: str) -> List[Dict[str, Any]]:
    out = []
    for r in _records().list_records("project_reports"):
        if r.get("project_id") == project_id and r.get("wf_status") == "approved" and r.get("seal_hash"):
            out.append(r)
    out.sort(key=lambda r: (str(r.get("number")), -int(r.get("version") or 1)))
    return out


BOREHOLE_FIELDS = ("BoreholeID", "ProjectName", "SiteName", "Latitude", "Longitude", "GroundElevation_mRL", "StartDate",
                   "EndDate", "DrillingMethod", "DrillRig", "CoreSize", "BoreholeDiameter_mm", "FinalDepth_m",
                   "CasingInstalled_mm", "GroundwaterDepth_m", "GroundwaterEncountered", "SoilDescription", "USCS_Class",
                   "Avg_SPT_N60", "Contractor", "LoggingGeologist")


def client_overview(client_ids: List[str]) -> Dict[str, Any]:
    records = _records()
    clients = [c for c in records.list_records("clients") if c.get("id") in set(client_ids or [])]
    rows = storage.load_reports()
    lab_all = records.list_records("lab_tests")
    projects = []
    for p in client_projects(client_ids):
        logs = sorted(project_logs(p, rows), key=lambda r: str(r.get("BoreholeID")))
        ids = {str(r.get("BoreholeID")).lower() for r in logs}
        lab = [t for t in lab_all if t.get("status") == "done" and t.get("authorised")
               and (t.get("project_id") == p["id"] or str(t.get("borehole_id") or "").lower() in ids)]
        projects.append({
            "id": p["id"], "code": p.get("code", ""), "name": p.get("name", ""), "location": p.get("location", ""),
            "status": p.get("status", ""),
            "reports": [{"id": r["id"], "number": r.get("number", ""), "version": int(r.get("version") or 1),
                         "title": r.get("title", ""), "date": r.get("date", ""), "current": r.get("status") != "superseded",
                         "code": seals.format_code(r.get("seal_code") or "")} for r in issued_reports(p["id"])],
            "boreholes": [{"id": r.get("BoreholeID", ""), "site": r.get("SiteName", ""), "start": r.get("StartDate", ""),
                           "final_depth": _num(r.get("FinalDepth_m")),
                           "gw_depth": _num(r.get("GroundwaterDepth_m")) if gw_encountered(r) else None} for r in logs],
            "lab_results": len(lab),
        })
    return {"clients": [{"id": c["id"], "name": c.get("name", "")} for c in clients], "projects": projects}


def client_project(client_ids: List[str], project_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in client_projects(client_ids) if p.get("id") == project_id), None)


def client_report(client_ids: List[str], report_id: str) -> Optional[Dict[str, Any]]:
    report = _get("project_reports", report_id)
    if not report or report.get("wf_status") != "approved" or not report.get("seal_hash"):
        return None
    if not client_project(client_ids, report.get("project_id") or ""):
        return None
    seal = seals.lookup(report["seal_hash"])
    if not seal:
        return None
    return {"content": seal["sealed"]["content"], "seal": seals.public_view(seal)}


def client_borehole(client_ids: List[str], borehole_id: str) -> Optional[Dict[str, Any]]:
    row = storage.get_report(borehole_id)
    if not row:
        return None
    if not any(_same(p.get("name"), row.get("ProjectName")) for p in client_projects(client_ids)):
        return None
    det = details.get_details(row["BoreholeID"])
    return {"report": {k: row.get(k, "") for k in BOREHOLE_FIELDS},
            "details": {"layers": det["layers"], "spt": det["spt"], "samples": det["samples"], "core": det["core"], "photos": []}}


def client_lab(client_ids: List[str], project_id: str) -> Optional[List[Dict[str, Any]]]:
    project = client_project(client_ids, project_id)
    if not project:
        return None
    ids = [str(r.get("BoreholeID")) for r in project_logs(project)]
    out = []
    for item in project_lab(project, ids):
        if item["authorised"]:
            out.append(item)
    return out
