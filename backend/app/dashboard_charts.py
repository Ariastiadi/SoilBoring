"""Distributions for the dashboard: depth ranges of the boreholes, the groundwater-encountered
rate, and the metres logged per soil class (USCS, ASTM D2487) in the strata."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

DEPTH_RANGES = [(0.0, 10.0, "0–10 m"), (10.0, 20.0, "10–20 m"), (20.0, 30.0, "20–30 m"), (30.0, 50.0, "30–50 m"),
                (50.0, float("inf"), "≥ 50 m")]


def _num(value: Any) -> Optional[float]:
    try:
        number = float(str(value).replace(",", ".")) if value not in (None, "") else None
    except ValueError:
        return None
    return number if number is not None and number == number else None


def groundwater_state(row: Dict[str, Any]) -> str:
    flag = str(row.get("GroundwaterEncountered") or "").strip().lower()
    if flag in ("true", "yes", "1") or (not flag and _num(row.get("GroundwaterDepth_m")) is not None):
        return "encountered"
    if flag in ("false", "no", "0"):
        return "not_encountered"
    return "not_recorded"


def distributions(rows: List[Dict[str, Any]], det: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    depth: Counter = Counter()
    for r in rows:
        d = _num(r.get("FinalDepth_m"))
        if d is None:
            continue
        label = next(label for lo, hi, label in DEPTH_RANGES if lo <= d < hi)
        depth[label] += 1
    gw = Counter(groundwater_state(r) for r in rows)
    known = gw["encountered"] + gw["not_encountered"]
    ids = {str(r.get("BoreholeID") or "") for r in rows}
    metres: Dict[str, float] = {}
    for bid, entry in det.items():
        if bid not in ids:
            continue
        for layer in entry.get("layers") or []:
            key = (layer.get("uscs") or "?").upper()
            metres[key] = metres.get(key, 0.0) + float(layer["base"]) - float(layer["top"])
    return {
        "depth_breakdown": [[label, depth[label]] for _, _, label in DEPTH_RANGES],
        "groundwater_breakdown": {"encountered": gw["encountered"], "not_encountered": gw["not_encountered"],
                                  "not_recorded": gw["not_recorded"]},
        "groundwater_rate_pct": round(gw["encountered"] / known * 100, 1) if known else None,
        "strata_uscs_m": {k: round(v, 1) for k, v in sorted(metres.items(), key=lambda kv: -kv[1])},
    }
