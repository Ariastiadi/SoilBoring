"""Data checks for administrators and managers: records that look wrong or incomplete, each
with a link to the record. Nothing is changed here.

Rules and their basis:

* Borehole IDs must be unique (also enforced when a log is saved); IDs that only differ in
  spaces, dashes or zero padding (BH-01, BH 1, bh01) are listed as possible duplicates.
* Strata must not overlap and should run without gaps from the ground surface to the final
  depth (ASTM D5434 field logging: the log describes the whole depth drilled).
* Strata, SPT, samples and core runs cannot be deeper than the hole's final depth.
* SPT (ASTM D1586 / SNI 4153:2008): the test stops at 50 blows in one 150 mm increment, at 100
  blows in total or with no advance over 10 blows, which is recorded as refusal. N above 100,
  or more than 50 blows in one increment, without a recorded refusal does not fit the method.
  A change of N by a factor of 3 and at least 20 blows between neighbouring tests in the same
  stratum is listed for checking (gravel, a boulder or a recording error); this is a screening
  rule, not a standard.
* Coordinates and ground elevation are needed for the location plan and the AGS4 LOCA group.
* Laboratory tests and sample receipts need a borehole that exists, and a sample reference that
  is in that borehole's samples.
* Results of finished tests should be authorised soon (ISO/IEC 17025 7.8.1.1); tests done but
  unauthorised for more than N days are listed.
* A CPT needs at least two readings to be interpreted.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from . import details, storage

Issue = Dict[str, Any]

CHECKS: List[tuple] = [
    ("duplicate_ids", "Duplicate borehole IDs", "error"),
    ("strata", "Overlapping or missing strata", "warn"),
    ("too_deep", "Depth data deeper than the hole", "error"),
    ("spt", "SPT N outliers", "warn"),
    ("location", "Missing coordinates or elevation", "warn"),
    ("orphans", "Samples and lab tests without a borehole", "error"),
    ("unauthorised", "Lab tests done but not authorised", "warn"),
    ("cpt_readings", "CPT without readings", "warn"),
]

TOLERANCE = 0.01  # m; depths are stored to the centimetre


def _num(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _bh(borehole_id: str) -> Dict[str, str]:
    return {"kind": "borehole", "id": borehole_id, "label": borehole_id}


def _issue(target: Dict[str, str], text: str, **values: Any) -> Issue:
    return {"target": target, "text": text, "vars": values}


def _norm_id(value: str) -> str:
    """BH-01, BH 1 and bh01 give the same key."""
    parts = re.findall(r"[a-z]+|\d+", value.lower())
    return "".join(p.lstrip("0") or "0" if p.isdigit() else p for p in parts)


def duplicate_ids(rows: List[Dict[str, Any]]) -> List[Issue]:
    out: List[Issue] = []
    exact: Dict[str, List[str]] = {}
    near: Dict[str, List[str]] = {}
    for r in rows:
        bid = str(r.get("BoreholeID") or "").strip()
        if not bid:
            continue
        exact.setdefault(bid.lower(), []).append(bid)
        near.setdefault(_norm_id(bid), []).append(bid)
    for ids in exact.values():
        if len(ids) > 1:
            out.append(_issue(_bh(ids[0]), "{id} is used by {n} logs", id=ids[0], n=len(ids)))
    for ids in near.values():
        distinct = sorted(set(ids), key=str.lower)
        if len({i.lower() for i in distinct}) > 1:
            out.append(_issue(_bh(distinct[0]), "{ids} may be the same borehole", ids=", ".join(distinct)))
    return out


def strata(rows: List[Dict[str, Any]], det: Dict[str, Dict[str, Any]]) -> List[Issue]:
    out: List[Issue] = []
    for r in rows:
        bid = r.get("BoreholeID", "")
        layers = sorted((det.get(bid) or {}).get("layers") or [], key=lambda x: (x["top"], x["base"]))
        if not layers:
            continue
        if layers[0]["top"] > TOLERANCE:
            out.append(_issue(_bh(bid), "{id}: no stratum from 0 to {top} m", id=bid, top=layers[0]["top"]))
        for a, b in zip(layers, layers[1:]):
            if b["top"] < a["base"] - TOLERANCE:
                out.append(_issue(_bh(bid), "{id}: strata {a} and {b} overlap", id=bid,
                                  a=f"{a['top']:g}–{a['base']:g} m", b=f"{b['top']:g}–{b['base']:g} m"))
            elif b["top"] > a["base"] + TOLERANCE:
                out.append(_issue(_bh(bid), "{id}: gap between {a} m and {b} m", id=bid, a=f"{a['base']:g}", b=f"{b['top']:g}"))
        final = _num(r.get("FinalDepth_m"))
        if final is not None and layers[-1]["base"] < final - 0.5:
            out.append(_issue(_bh(bid), "{id}: strata end at {base} m, the hole at {final} m", id=bid,
                              base=f"{layers[-1]['base']:g}", final=f"{final:g}"))
    return out


def too_deep(rows: List[Dict[str, Any]], det: Dict[str, Dict[str, Any]]) -> List[Issue]:
    out: List[Issue] = []
    for r in rows:
        bid = r.get("BoreholeID", "")
        final = _num(r.get("FinalDepth_m"))
        d = det.get(bid) or {}
        if final is None:
            continue
        deepest = [("Strata", max((x["base"] for x in d.get("layers") or []), default=None)),
                   ("SPT", max((x["depth"] for x in d.get("spt") or []), default=None)),
                   ("Samples", max((x.get("base") or x["top"] for x in d.get("samples") or []), default=None)),
                   ("Core runs", max((x["base"] for x in d.get("core") or []), default=None))]
        for what, depth in deepest:
            if depth is not None and depth > final + TOLERANCE:
                out.append(_issue(_bh(bid), "{id}: {what} reach {depth} m, the final depth is {final} m",
                                  id=bid, what=what, depth=f"{depth:g}", final=f"{final:g}"))
    return out


def spt(rows: List[Dict[str, Any]], det: Dict[str, Dict[str, Any]]) -> List[Issue]:
    out: List[Issue] = []
    for r in rows:
        bid = r.get("BoreholeID", "")
        d = det.get(bid) or {}
        layers = d.get("layers") or []
        tests = sorted(d.get("spt") or [], key=lambda x: x["depth"])

        def layer_of(depth: float) -> Optional[int]:
            return next((i for i, x in enumerate(layers) if x["top"] <= depth < x["base"]), None)

        for t in tests:
            refusal = t.get("penetration_mm") not in (None, "") and int(t["penetration_mm"]) < 300
            n = int(t.get("inc1") or 0) + int(t.get("inc2") or 0)
            most = max(int(t.get("seat") or 0), int(t.get("inc1") or 0), int(t.get("inc2") or 0))
            if not refusal and (n > 100 or most > 50):
                out.append(_issue(_bh(bid), "{id} at {depth} m: N = {n} without a recorded refusal", id=bid, depth=f"{t['depth']:g}", n=n))
        for a, b in zip(tests, tests[1:]):
            na, nb = a.get("n"), b.get("n")
            if na is None or nb is None or "/" in str(a.get("reported", "")) or "/" in str(b.get("reported", "")):
                continue
            same = layer_of(a["depth"]) is not None and layer_of(a["depth"]) == layer_of(b["depth"])
            lo, hi = sorted((float(na), float(nb)))
            if same and hi - lo >= 20 and hi >= 3 * max(lo, 1):
                out.append(_issue(_bh(bid), "{id}: N jumps from {a} to {b} between {da} and {db} m in one stratum",
                                  id=bid, a=int(na), b=int(nb), da=f"{a['depth']:g}", db=f"{b['depth']:g}"))
    return out


def location(rows: List[Dict[str, Any]], cpt: List[Dict[str, Any]]) -> List[Issue]:
    out: List[Issue] = []
    for r in rows:
        bid = r.get("BoreholeID", "")
        lat, lon = _num(r.get("Latitude")), _num(r.get("Longitude"))
        if lat is None or lon is None or (lat == 0 and lon == 0):
            out.append(_issue(_bh(bid), "{id}: no coordinates", id=bid))
        if _num(r.get("GroundElevation_mRL")) is None:
            out.append(_issue(_bh(bid), "{id}: no ground elevation", id=bid))
    for c in cpt:
        target = {"kind": "cpt", "id": c["id"], "label": c.get("test_id", "")}
        if _num(c.get("latitude")) is None or _num(c.get("longitude")) is None:
            out.append(_issue(target, "CPT {id}: no coordinates", id=c.get("test_id", "")))
    return out


def orphans(rows: List[Dict[str, Any]], det: Dict[str, Dict[str, Any]], lab: List[Dict[str, Any]],
            receipts: List[Dict[str, Any]]) -> List[Issue]:
    out: List[Issue] = []
    known = {str(r.get("BoreholeID") or "").lower(): r.get("BoreholeID", "") for r in rows}
    refs = {bid.lower(): {details.ascii_ref(s.get("ref") or "") for s in (d.get("samples") or [])} for bid, d in det.items()}
    for kind, items, label in (("lab_test", lab, "Lab test"), ("sample_receipt", receipts, "Sample receipt")):
        for t in items:
            bid = str(t.get("borehole_id") or "")
            target = {"kind": kind, "id": t["id"], "label": f"{bid} {t.get('sample_ref', '')}".strip()}
            if not bid or bid.lower() not in known:
                out.append(_issue(target, "{what} {sample}: borehole {id} does not exist", what=label,
                                  sample=t.get("sample_ref", ""), id=bid or "–"))
            elif t.get("sample_ref") and refs.get(bid.lower()) is not None and refs[bid.lower()] \
                    and details.ascii_ref(t["sample_ref"]) not in refs[bid.lower()]:
                out.append(_issue(target, "{what} {sample}: sample not in the samples of {id}", what=label,
                                  sample=t["sample_ref"], id=known[bid.lower()]))
    return out


def unauthorised(lab: List[Dict[str, Any]], days: int, today: date) -> List[Issue]:
    out: List[Issue] = []
    for t in lab:
        if t.get("status") != "done" or t.get("authorised"):
            continue
        when = t.get("tested") or str(t.get("updated_at") or "")[:10]
        try:
            since = (today - datetime.strptime(when[:10], "%Y-%m-%d").date()).days
        except ValueError:
            continue
        if since > days:
            target = {"kind": "lab_test", "id": t["id"], "label": f"{t.get('borehole_id', '')} {t.get('sample_ref', '')}"}
            out.append(_issue(target, "{sample}: done {n} days ago, not authorised", sample=target["label"], n=since))
    return out


def cpt_readings(cpt: List[Dict[str, Any]]) -> List[Issue]:
    return [_issue({"kind": "cpt", "id": c["id"], "label": c.get("test_id", "")}, "CPT {id}: {n} readings", id=c.get("test_id", ""),
                   n=len(c.get("readings") or [])) for c in cpt if len(c.get("readings") or []) < 2]


def run(days: int = 7, today: Optional[date] = None) -> Dict[str, Any]:
    from . import records

    today = today or date.today()
    rows = storage.load_reports()
    det = details.all_details()  # SPT rows keep seat, increments and penetration next to N
    lab = records.list_records("lab_tests")
    cpt = records.list_records("cpt")
    receipts = records.list_records("sample_receipts")
    found: Dict[str, Callable[[], List[Issue]]] = {
        "duplicate_ids": lambda: duplicate_ids(rows),
        "strata": lambda: strata(rows, det),
        "too_deep": lambda: too_deep(rows, det),
        "spt": lambda: spt(rows, det),
        "location": lambda: location(rows, cpt),
        "orphans": lambda: orphans(rows, det, lab, receipts),
        "unauthorised": lambda: unauthorised(lab, days, today),
        "cpt_readings": lambda: cpt_readings(cpt),
    }
    checks = []
    for key, title, severity in CHECKS:
        items = found[key]()
        checks.append({"key": key, "title": title, "severity": severity, "count": len(items), "items": items[:500]})
    return {"checks": checks, "days": days, "boreholes": len(rows), "total": sum(c["count"] for c in checks)}

