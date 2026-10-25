"""Runs an engineering analysis from the inputs stored with it.

Pile capacity and liquefaction read the borehole's depth data (strata and SPT) and the
laboratory results of its samples, so the analysis follows the field and lab data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import details, engineering, records, storage


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
            if t.get("test_type") == "density" and res.get("gamma_bulk") is not None:
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
    raise ValueError("Choose an analysis type")
