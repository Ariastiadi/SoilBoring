"""Runs an engineering analysis from the inputs stored with it.

Pile capacity and liquefaction read the borehole's depth data (strata and SPT) and the
laboratory results of its samples, so the analysis follows the field and lab data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import calc_field, calcbase, details, engineering, records, seismic, storage


def _opt(inputs: Dict[str, Any], key: str) -> Optional[float]:
    value = inputs.get(key)
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc


def _req(inputs: Dict[str, Any], key: str, default: Optional[float] = None) -> float:
    value = _opt(inputs, key)
    if value is None:
        if default is None:
            raise ValueError(f"{key} is required")
        return default
    return value


def _borehole(inputs: Dict[str, Any]) -> Dict[str, Any]:
    borehole_id = str(inputs.get("borehole_id") or "").strip()
    if not borehole_id:
        raise ValueError("Choose a borehole")
    report = storage.get_report(borehole_id)
    if report is None:
        raise ValueError("Report not found")
    depth = details.get_details(report["BoreholeID"])
    if not depth["layers"] or not depth["spt"]:
        raise ValueError("This borehole needs strata and SPT data first")
    return {"report": report, "depth": depth}


def _lab_by_depth(borehole_id: str) -> List[Dict[str, Any]]:
    return [t for t in records.list_records("lab_tests")
            if str(t.get("borehole_id") or "").lower() == borehole_id.lower() and t.get("status") == "done"]


def _layer_props(layers: List[Dict[str, Any]], lab: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strata with unit weight, fines and PI taken from lab tests inside each layer."""
    out = []
    for layer in layers:
        inside = [t for t in lab if layer["top"] - 1e-9 <= float(t.get("depth_top") or 0) < layer["base"]]
        props: Dict[str, Any] = {"top": layer["top"], "base": layer["base"], "uscs": layer.get("uscs") or ""}
        for t in inside:
            res = t.get("results") or {}
            if t.get("test_type") == "grain_size" and res.get("fines") is not None:
                props["fines"] = res["fines"]
            if t.get("test_type") == "atterberg" and res.get("pi") is not None:
                props["pi"] = res["pi"]
            if t.get("test_type") in ("density", "moisture") and res.get("gamma_bulk") is not None:
                props["gamma"] = res["gamma_bulk"]
                props["gamma_sat"] = max(res["gamma_bulk"], res["gamma_bulk"] + 1)
        out.append(props)
    return out


def _groundwater(report: Dict[str, Any]) -> Optional[float]:
    if str(report.get("GroundwaterEncountered", "")).strip().lower() in ("false", "0", "no"):
        return None
    try:
        return float(str(report.get("GroundwaterDepth_m") or ""))
    except (TypeError, ValueError):
        return None


def run(kind: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "bearing":
        L = _opt(inputs, "L")
        result = engineering.bearing_capacity_shallow(
            B=_req(inputs, "B"), L=L if L else None, Df=_req(inputs, "Df", 0.0),
            c=_req(inputs, "c", 0.0), phi_deg=_req(inputs, "phi_deg", 0.0), gamma=_req(inputs, "gamma", 18.0),
            gw_depth=_opt(inputs, "gw_depth"), gamma_sat=_opt(inputs, "gamma_sat"),
            fs=_req(inputs, "fs", 3.0),
        )
        result["summary"] = f"q_allow = {result['q_allow']:g} kPa (qu = {result['qu']:g} kPa)"
        return result
    if kind == "pile":
        data = _borehole(inputs)
        spt = [{"depth": s["depth"], "n": s.get("n") if s.get("n") is not None else s["inc1"] + (s.get("inc2") or 0)} for s in data["depth"]["spt"]]
        layers = [{"top": l["top"], "base": l["base"], "uscs": l.get("uscs") or ""} for l in data["depth"]["layers"]]
        diameter, pile_type = _req(inputs, "diameter"), str(inputs.get("pile_type") or "driven")
        fs_shaft, fs_tip = _req(inputs, "fs_shaft", 2.5), _req(inputs, "fs_tip", 2.5)
        result = engineering.pile_capacity_decourt(diameter=diameter, length=_req(inputs, "length"), spt=spt, layers=layers,
                                                   pile_type=pile_type, fs_shaft=fs_shaft, fs_tip=fs_tip)
        try:
            result["profile"] = engineering.pile_capacity_profile(diameter=diameter, spt=spt, layers=layers, pile_type=pile_type,
                                                                  fs_shaft=fs_shaft, fs_tip=fs_tip)["profile"]
        except ValueError:
            result["profile"] = []
        result["summary"] = f"Q_allow = {result['Qallow']:g} kN, L = {result['inputs'].get('length', inputs.get('length'))} m" if isinstance(result.get("inputs"), dict) else f"Q_allow = {result['Qallow']:g} kN"
        return result
    if kind == "settlement":
        layers = inputs.get("layers") or []
        if not isinstance(layers, list) or not layers:
            raise ValueError("Add at least one compressible layer")
        L = _opt(inputs, "L")
        result = engineering.consolidation_settlement(
            layers=layers, q=_req(inputs, "q"), B=_req(inputs, "B"), L=L if L else None,
            Df=_req(inputs, "Df", 0.0), gw_depth=_opt(inputs, "gw_depth"))
        result["summary"] = f"Settlement = {result['total_settlement_mm']:g} mm"
        return result
    if kind == "liquefaction":
        data = _borehole(inputs)
        report = data["report"]
        gw = _opt(inputs, "gw_depth")
        if gw is None:
            gw = _groundwater(report)
        if gw is None:
            raise ValueError("Enter the groundwater depth")
        spt = [{"depth": s["depth"], "n": s.get("n") if s.get("n") is not None else s["inc1"] + (s.get("inc2") or 0)} for s in data["depth"]["spt"]]
        layers = _layer_props(data["depth"]["layers"], _lab_by_depth(report["BoreholeID"]))
        hole = _opt(inputs, "borehole_diameter_mm")
        if hole is None:
            try:
                hole = float(report.get("BoreholeDiameter_mm") or 100)
            except ValueError:
                hole = 100.0
        result = engineering.liquefaction_spt(
            spt=spt, layers=layers, gw_depth=gw, amax_g=_req(inputs, "amax_g"),
            magnitude=_req(inputs, "magnitude", 7.5), energy_ratio=_req(inputs, "energy_ratio", 60.0),
            borehole_diameter_mm=hole)
        summary = result.get("summary") or {}
        count = summary.get("n_liquefiable", 0)
        shallowest = summary.get("shallowest_liquefiable_depth")
        result["details"] = summary
        result["summary"] = (f"{count} SPT liquefiable, shallowest at {shallowest:g} m" if count and shallowest is not None
                             else "No liquefiable SPT")
        return result
    if kind == "bearing_table":
        return _bearing_table(inputs)
    if kind == "site_class":
        pairs: List[Tuple[float, float]] = []
        if str(inputs.get("borehole_id") or "").strip():
            found = _borehole(inputs)
            pairs = [(float(x["depth"]), float(x.get("n") if x.get("n") is not None else x["inc1"] + (x.get("inc2") or 0)))
                     for x in found["depth"]["spt"]]
        return seismic.site_class_analysis(inputs, pairs)
    if kind == "spt_correction":
        return _spt_correction(inputs)
    if kind == "retaining_wall":
        from . import eng_wall
        return eng_wall.analyse(inputs)
    if kind == "slope":
        from . import eng_slope
        return eng_slope.analyse(inputs)
    raise ValueError("Choose an analysis type")


def _list(inputs: Dict[str, Any], key: str, label: str) -> List[float]:
    text = str(inputs.get(key) or "").replace(";", " ").replace(",", " ")
    values = []
    for part in text.split():
        try:
            values.append(float(part))
        except ValueError as exc:
            raise ValueError(f"{label}: enter numbers separated by spaces") from exc
    if not values or len(values) > 12:
        raise ValueError(f"{label}: enter 1 to 12 values")
    return values


def _bearing_table(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Allowable bearing pressure for several footing widths and depths at once."""
    widths = _list(inputs, "B_list", "Footing widths B")
    depths = _list(inputs, "Df_list", "Founding depths Df")
    ratio = _opt(inputs, "LB") or 1.0
    fs = _req(inputs, "fs", 3.0)
    rows = []
    best = None
    for df in depths:
        row: List[Any] = [df]
        for b in widths:
            out = engineering.bearing_capacity_shallow(
                B=b, L=b * ratio if ratio < 50 else None, Df=df, c=_req(inputs, "c", 0.0), phi_deg=_req(inputs, "phi_deg", 0.0),
                gamma=_req(inputs, "gamma", 18.0), gw_depth=_opt(inputs, "gw_depth"), gamma_sat=_opt(inputs, "gamma_sat"), fs=fs)
            row.append(round(out["q_allow"], 1))
            best = out["q_allow"] if best is None else max(best, out["q_allow"])
        rows.append(row)
    notes = ["Each cell is q_allow = qu / FS in kPa for that width (columns) and founding depth (rows).",
             "L/B = 1 is a square footing; enter a large L/B (e.g. 100) for a strip footing.",
             "Preliminary estimate only; results must be checked by a qualified geotechnical engineer."]
    if fs < 3:
        notes.insert(0, "Factor of safety below 3: SNI 8460:2017 asks for FS ≥ 3 for shallow foundations.")
    charts = [calcbase.chart("Allowable bearing pressure", calcbase.axis("Footing width B (m)"), calcbase.axis("q_allow (kPa)"),
                             *[calcbase.series(f"Df = {r[0]:g} m", list(zip(widths, r[1:])), "both") for r in rows])]
    return calcbase.result(
        summary=[("q_allow max", round(best or 0, 1), "kPa"), ("FS", fs, "")],
        values=[("Factor of safety", fs, ""), ("L/B", ratio, "")],
        tables=[calcbase.table("q_allow (kPa)", ["Df (m) / B (m)"] + [f"{b:g}" for b in widths], rows)],
        charts=charts, notes=notes, method="Vesic bearing capacity factors with De Beer shape and Hansen depth factors")


def _spt_correction(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """N60 and (N1)60 for every SPT of a borehole; soil type and unit weight come from the strata."""
    data = _borehole(inputs)
    report = data["report"]
    layers = _layer_props(data["depth"]["layers"], _lab_by_depth(report["BoreholeID"]))
    gw = _opt(inputs, "gw_depth")
    if gw is None:
        gw = _groundwater(report)
    gamma = _opt(inputs, "gamma")
    rows = []
    for s in data["depth"]["spt"]:
        depth = float(s["depth"])
        n = s.get("n") if s.get("n") is not None else s["inc1"] + (s.get("inc2") or 0)
        layer = next((x for x in layers if x["top"] - 1e-9 <= depth < x["base"]), layers[-1] if layers else {})
        rows.append({"depth": depth, "n": n, "penetration_mm": s.get("penetration_mm"),
                     "uscs": layer.get("uscs") or "", "unit_weight": layer.get("gamma") or gamma})
    header = {
        "energy_ratio": _req(inputs, "energy_ratio", 60.0),
        "borehole_diameter": _opt(inputs, "borehole_diameter_mm") or _number(report.get("BoreholeDiameter_mm")) or 100.0,
        "sampler": "standard" if str(inputs.get("sampler_liners") or "no") == "yes" else "no_liner",
        "stick_up": _opt(inputs, "rod_extra_m") or 0.0,
        "groundwater": gw,
    }
    return calc_field.spt_correction(header, rows)


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
