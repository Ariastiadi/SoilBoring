"""Shared shape of worksheet calculation results.

Every calculation returns a dict the interface renders without knowing the test:

    {
      "summary": "Label = value unit; Label = value unit",  # one line for lists
      "values": [{"label": str, "value": number|str|None, "unit": str}],
      "tables": [{"title": str, "columns": [str], "rows": [[...]]}],
      "charts": [chart, ...],
      "notes": [str],          # fixed sentences (translated in the interface)
      "method": str,
      "lab": {...}             # lab tests only: values copied into the test results
    }

A chart is {"title", "x": axis, "y": axis, "series": [{"name", "points": [[x, y], ...],
"style": "line"|"points"|"both", "dash": bool}]} where an axis is {"label", "log": bool,
"reverse": bool}. A "value" chart has {"kind": "value", "points": [[x, y, v]], "value_label",
"log_value"} instead of series (e.g. a resistivity pseudo-section).
Labels are English; the interface translates them.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

Number = Union[int, float]


class CalcError(ValueError):
    """Input that cannot be calculated; the message is shown to the user."""


def num(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        out = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def need(data: Dict[str, Any], key: str, label: str) -> float:
    value = num(data.get(key))
    if value is None:
        raise CalcError(f"{label} is required")
    return value


def rows_of(data: Dict[str, Any], key: str, *required: str) -> List[Dict[str, Any]]:
    """Rows of an item table that have all the required columns filled in."""
    out = []
    for row in data.get(key) or []:
        if not isinstance(row, dict):
            continue
        if all(num(row.get(k)) is not None for k in required):
            out.append(row)
    return out


def rnd(value: Optional[float], digits: int = 3) -> Optional[float]:
    """Rounded to a sensible number of significant digits for display."""
    if value is None or not math.isfinite(value):
        return None
    if value == 0:
        return 0.0
    magnitude = int(math.floor(math.log10(abs(value))))
    return round(value, max(0, digits - 1 - magnitude))


def fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def result(summary: Sequence[Tuple[str, Any, str]] = (), values: Sequence[Tuple[str, Any, str]] = (),
           tables: Iterable[Dict[str, Any]] = (), charts: Iterable[Dict[str, Any]] = (),
           notes: Iterable[str] = (), method: str = "", lab: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "summary": "; ".join(f"{label} = {fmt(value)}{(' ' + unit) if unit else ''}"
                             for label, value, unit in summary if value is not None),
        "values": [{"label": label, "value": value, "unit": unit} for label, value, unit in values],
        "tables": list(tables),
        "charts": list(charts),
        "notes": list(notes),
        "method": method,
    }
    if lab is not None:
        out["lab"] = {k: v for k, v in lab.items() if v is not None}
    return out


def axis(label: str, log: bool = False, reverse: bool = False) -> Dict[str, Any]:
    return {"label": label, "log": log, "reverse": reverse}


def series(name: str, points: Iterable[Tuple[Any, Any]], style: str = "both", dash: bool = False) -> Dict[str, Any]:
    pts = [[rnd(float(x), 5), rnd(float(y), 5)] for x, y in points
           if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    return {"name": name, "points": pts, "style": style, "dash": dash}


def chart(title: str, x: Dict[str, Any], y: Dict[str, Any], *data: Dict[str, Any]) -> Dict[str, Any]:
    return {"title": title, "x": x, "y": y, "series": [s for s in data if s["points"]]}


def table(title: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> Dict[str, Any]:
    return {"title": title, "columns": list(columns),
            "rows": [[rnd(v, 4) if isinstance(v, float) else v for v in row] for row in rows]}


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float]:
    """Least squares y = a + b x; returns (a, b, r²)."""
    n = len(xs)
    if n < 2:
        raise CalcError("At least two points are needed")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise CalcError("The points must not all have the same value")
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = (sxy * sxy) / (sxx * syy) if syy else 1.0
    return a, b, r2


def interpolate(x: float, xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Linear interpolation on increasing xs; None outside the range."""
    for i in range(1, len(xs)):
        x0, x1 = xs[i - 1], xs[i]
        if (x0 <= x <= x1) or (x1 <= x <= x0):
            if x1 == x0:
                return ys[i]
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)
    return None


def thin(points: List[Any], limit: int = 400) -> List[Any]:
    """Every n-th point so long profiles stay small."""
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    kept = points[::step]
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept
