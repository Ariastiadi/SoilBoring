"""Monitoring instruments: piezometers (standpipe and vibrating wire), groundwater wells,
inclinometers, settlement plates and extensometers, with their readings as a time series.

``compute_instrument`` is the COMPUTE_HOOK of the ``instruments`` entity (entities_monitor.py). On
every save it sorts the readings, works out the latest value, the change since the base reading, the
rate per day over the last interval and the alarm state against the alert and action levels, and
stores a calcbase result (values, tables, charts, notes) the interface shows like a worksheet.

Method after Dunnicliff (1993) Geotechnical Instrumentation for Monitoring Field Performance (base
readings, alert/action levels and rates), ISO 18674-1:2015 (general rules) and ASTM D6230 for the
probe inclinometer: cumulative displacement is the sum of the incremental displacements from the
fixed bottom of the casing up to each depth, resultant = √(A² + B²).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .calcbase import axis, chart, num, result, rnd, series, table

Row = Dict[str, Any]

TYPES = [
    ("standpipe", "Standpipe piezometer"), ("vw_piezometer", "Vibrating wire piezometer"), ("gw_well", "Groundwater monitoring well"),
    ("inclinometer", "Inclinometer"), ("settlement_plate", "Settlement plate"), ("extensometer", "Extensometer"),
]
DEFAULT_UNITS = {"standpipe": "m", "vw_piezometer": "kPa", "gw_well": "m", "inclinometer": "mm", "settlement_plate": "mm",
                 "extensometer": "mm"}
ALARM_STATES = [("no_data", "No readings"), ("normal", "Normal"), ("alert", "Alert"), ("action", "Action")]
ALARM_ON = [("change", "Change since the base reading (either direction)"), ("above", "Reading rises to the level"),
            ("below", "Reading falls to the level")]
STATE_LABEL = dict(ALARM_STATES)


def _day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _state(metric: Optional[float], alert: Optional[float], action: Optional[float], rising: bool) -> str:
    if metric is None:
        return "no_data"

    def hit(level: Optional[float]) -> bool:
        return level is not None and (metric >= level if rising else metric <= level)
    if hit(action):
        return "action"
    if hit(alert):
        return "alert"
    return "normal"


def _level_notes(record: Row, basis: str) -> List[str]:
    alert, action = num(record.get("alert_level")), num(record.get("action_level"))
    notes: List[str] = []
    if alert is None and action is None:
        notes.append("No alert or action level is set; the alarm state stays normal.")
    elif alert is not None and action is not None:
        if basis == "below" and alert < action:
            notes.append("For a falling reading the alert level should be above the action level; check the levels.")
        elif basis != "below" and alert > action:
            notes.append("The alert level should come before the action level; check the levels.")
    if basis == "change" and ((alert is not None and alert < 0) or (action is not None and action < 0)):
        notes.append("Levels on the change since the base reading are magnitudes; enter them as positive numbers.")
    return notes


def _threshold_lines(x0: float, x1: float, alert: Optional[float], action: Optional[float], both_signs: bool) -> List[Dict[str, Any]]:
    out = []
    for name, level in (("Alert level", alert), ("Action level", action)):
        if level is None:
            continue
        out.append(series(name, [(x0, level), (x1, level)], style="line", dash=True))
        if both_signs and level:
            out.append(series(name, [(x0, -level), (x1, -level)], style="line", dash=True))
    return out


def _clear(record: Row) -> None:
    for key in ("latest_date", "latest_value", "change", "rate_per_day", "max_change"):
        record[key] = None
    record["reading_count"] = 0
    record["alarm_state"] = "no_data"


def compute_instrument(record: Row) -> None:
    kind = str(record.get("type") or "")
    _clear(record)
    if kind == "inclinometer":
        _inclinometer(record)
    else:
        _series(record)


# --------------------------------------------------------------------------- #
# One value per reading: piezometers, wells, settlement plates, extensometers
# --------------------------------------------------------------------------- #

def _series(record: Row) -> None:
    unit = str(record.get("unit") or DEFAULT_UNITS.get(str(record.get("type") or ""), ""))
    rows = [r for r in record.get("readings") or [] if isinstance(r, dict) and _day(r.get("date")) and num(r.get("value")) is not None]
    rows.sort(key=lambda r: str(r.get("date")))
    record["readings"] = rows
    record["reading_count"] = len(rows)
    basis = str(record.get("alarm_on") or "change")
    alert, action = num(record.get("alert_level")), num(record.get("action_level"))
    rate_alert = num(record.get("rate_alert"))
    notes = _level_notes(record, basis)
    if not rows:
        record["results"] = {}
        record["summary"] = ""
        return
    base = num(record.get("base_value"))
    base_day = _day(record.get("base_date")) or _day(rows[0]["date"])
    if base is None:
        base = float(rows[0]["value"])
        notes.append("No base reading entered: the first reading is the base.")
    assert base_day is not None
    install = _day(record.get("install_date"))
    if install and any((_day(r["date"]) or install) < install for r in rows):
        notes.append("Some readings are dated before the installation date; check the dates.")
    dates = [str(r["date"]) for r in rows]
    if len(set(dates)) < len(dates):
        notes.append("More than one reading on the same date; the rate uses the last reading of each date.")
    elevation = num(record.get("elevation"))
    as_depth = bool(record.get("reading_is_depth")) and elevation is not None
    table_rows: List[List[Any]] = []
    pts: List[Tuple[float, float]] = []
    change_pts: List[Tuple[float, float]] = []
    first_alarm: Dict[str, str] = {}
    by_day: Dict[str, float] = {}
    for r in rows:
        v = float(r["value"])
        d = _day(r["date"])
        assert d is not None
        days = (d - base_day).days
        change = v - base
        metric = abs(change) if basis == "change" else v
        st = _state(metric, alert, action, basis != "below")
        for level in ("alert", "action"):
            if st in (level, "action") and level not in first_alarm:
                first_alarm[level] = str(r["date"])
        line = [str(r["date"]), days, v, rnd(change, 5)]
        if as_depth:
            line.append(rnd(elevation - v, 5) if elevation is not None else None)
        line += [STATE_LABEL[st], str(r.get("note") or "")]
        table_rows.append(line)
        pts.append((days, v))
        change_pts.append((days, change))
        by_day[str(r["date"])] = v
    days_sorted = sorted(by_day)
    rate = None
    if len(days_sorted) >= 2:
        d1, d0 = _day(days_sorted[-1]), _day(days_sorted[-2])
        assert d1 is not None and d0 is not None
        span = (d1 - d0).days
        if span > 0:
            rate = (by_day[days_sorted[-1]] - by_day[days_sorted[-2]]) / span
    latest = float(rows[-1]["value"])
    change = latest - base
    metric = abs(change) if basis == "change" else latest
    state = _state(metric, alert, action, basis != "below")
    if rate_alert is not None and rate is not None and abs(rate) >= rate_alert and state == "normal":
        state = "alert"
        notes.append("The rate over the last interval reached the alert rate.")
    record.update({
        "latest_date": str(rows[-1]["date"]), "latest_value": rnd(latest, 6), "change": rnd(change, 5),
        "rate_per_day": rnd(rate, 4), "max_change": rnd(max(abs(c) for _, c in change_pts), 5), "alarm_state": state,
    })
    x1 = max(1.0, max(p[0] for p in pts))
    x0 = min(0.0, min(p[0] for p in pts))
    charts = [chart("Reading against time", axis("Days since the base reading"), axis("Reading"),
                    series("Reading", pts),
                    *(_threshold_lines(x0, x1, alert, action, False) if basis != "change" else []))]
    if basis == "change":
        charts.append(chart("Change since the base reading", axis("Days since the base reading"),
                            axis("Change since the base reading"), series("Change", change_pts),
                            *_threshold_lines(x0, x1, alert, action, True)))
    if as_depth:
        charts.append(chart("Water level against time", axis("Days since the base reading"), axis("Water level (mRL)"),
                            series("Water level", [(x, (elevation or 0) - y) for x, y in pts])))
    columns = ["Date", "Day", "Reading", "Change"] + (["Water level (mRL)"] if as_depth else []) + ["Alarm", "Note"]
    values = [("Latest reading", rnd(latest, 6), unit), ("Latest reading on", str(rows[-1]["date"]), ""),
              ("Base reading", rnd(base, 6), unit), ("Base date", base_day.isoformat(), ""),
              ("Change since the base reading", rnd(change, 5), unit),
              ("Rate over the last interval", rnd(rate, 4), f"{unit}/day" if unit else "per day"),
              ("Largest change", record["max_change"], unit), ("Readings", len(rows), ""),
              ("Alarm state", STATE_LABEL[state], "")]
    if as_depth and elevation is not None:
        values.insert(1, ("Water level", rnd(elevation - latest, 5), "mRL"))
    if "alert" in first_alarm:
        values.append(("Alert level first reached on", first_alarm["alert"], ""))
    if "action" in first_alarm:
        values.append(("Action level first reached on", first_alarm["action"], ""))
    notes.append("Change = reading − base reading; rate = change between the last two reading dates / days between them.")
    if basis == "change":
        notes.append("The alarm compares the size of the change since the base reading with the alert and action levels.")
    elif basis == "above":
        notes.append("The alarm is raised when the reading rises to the alert or action level.")
    else:
        notes.append("The alarm is raised when the reading falls to the alert or action level.")
    record["results"] = result(
        summary=[("Latest reading", rnd(latest, 6), unit), ("Change", rnd(change, 5), unit),
                 ("Rate per day", rnd(rate, 4), f"{unit}/day" if unit else "per day")],
        values=values,
        tables=[table("Readings", columns, list(reversed(table_rows)), key=["Date", "Reading", "Change", "Alarm"], note="Note")],
        charts=charts, notes=notes,
        method="Time series against the base reading with alert and action levels (Dunnicliff 1993; ISO 18674-1)")
    record["summary"] = str(record["results"]["summary"])[:300]


# --------------------------------------------------------------------------- #
# Inclinometer: displacement profiles per survey date
# --------------------------------------------------------------------------- #

def incline_profiles(rows: List[Row], incremental: bool) -> Dict[str, List[Tuple[float, float, float]]]:
    """{date: [(depth, cumulative A, cumulative B)] from the top down}. Incremental values are summed
    from the bottom (fixed toe of the casing) upwards."""
    surveys: Dict[str, Dict[float, Tuple[float, float]]] = {}
    for r in rows:
        d, z = str(r.get("date") or "")[:10], num(r.get("depth"))
        if not _day(d) or z is None:
            continue
        surveys.setdefault(d, {})[z] = (num(r.get("a")) or 0.0, num(r.get("b")) or 0.0)
    out: Dict[str, List[Tuple[float, float, float]]] = {}
    for d in sorted(surveys):
        depths = sorted(surveys[d], reverse=True)  # bottom first
        prof: List[Tuple[float, float, float]] = []
        ca = cb = 0.0
        for z in depths:
            a, b = surveys[d][z]
            if incremental:
                ca += a
                cb += b
                prof.append((z, ca, cb))
            else:
                prof.append((z, a, b))
        out[d] = sorted(prof)
    return out


def _inclinometer(record: Row) -> None:
    rows = [r for r in record.get("profile") or [] if isinstance(r, dict)]
    rows.sort(key=lambda r: (str(r.get("date") or ""), num(r.get("depth")) or 0.0))
    record["profile"] = rows
    incremental = str(record.get("incl_input") or "cumulative") == "incremental"
    profiles = incline_profiles(rows, incremental)
    record["reading_count"] = len(profiles)
    alert, action = num(record.get("alert_level")), num(record.get("action_level"))
    rate_alert = num(record.get("rate_alert"))
    notes = _level_notes(record, "change")
    if not profiles:
        record["results"] = {}
        record["summary"] = ""
        return
    dates = list(profiles)
    base_day = _day(dates[0])
    assert base_day is not None
    survey_rows: List[List[Any]] = []
    max_pts: List[Tuple[float, float]] = []
    maxima: Dict[str, Tuple[float, float]] = {}
    for d in dates:
        prof = profiles[d]
        res = [(z, math.hypot(a, b)) for z, a, b in prof]
        z_max, r_max = max(res, key=lambda x: x[1])
        maxima[d] = (r_max, z_max)
        day = _day(d)
        assert day is not None
        max_pts.append(((day - base_day).days, r_max))
        st = _state(r_max, alert, action, True)
        survey_rows.append([d, (day - base_day).days, rnd(r_max, 4), rnd(z_max, 4), STATE_LABEL[st]])
    latest = dates[-1]
    rate = None
    if len(dates) >= 2:
        prev = dates[-2]
        d1, d0 = _day(latest), _day(prev)
        assert d1 is not None and d0 is not None
        span = (d1 - d0).days
        before = {z: (a, b) for z, a, b in profiles[prev]}
        moves = [math.hypot(a - before[z][0], b - before[z][1]) for z, a, b in profiles[latest] if z in before]
        if span > 0 and moves:
            rate = max(moves) / span
    r_max, z_max = maxima[latest]
    state = _state(r_max, alert, action, True)
    if rate_alert is not None and rate is not None and rate >= rate_alert and state == "normal":
        state = "alert"
        notes.append("The rate over the last interval reached the alert rate.")
    record.update({"latest_date": latest, "latest_value": rnd(r_max, 4), "change": rnd(r_max, 4), "rate_per_day": rnd(rate, 4),
                   "max_change": rnd(max(m[0] for m in maxima.values()), 4), "alarm_state": state})
    shown = dates[-4:]
    charts = [chart("Cumulative displacement A against depth", axis("Displacement A (mm)"), axis("Depth (m)", reverse=True),
                    *[series(d, [(a, z) for z, a, _ in profiles[d]], style="line") for d in shown]),
              chart("Cumulative displacement B against depth", axis("Displacement B (mm)"), axis("Depth (m)", reverse=True),
                    *[series(d, [(b, z) for z, _, b in profiles[d]], style="line") for d in shown]),
              chart("Largest displacement against time", axis("Days since the base reading"), axis("Resultant displacement (mm)"),
                    series("Largest resultant", max_pts),
                    *_threshold_lines(min(0.0, max_pts[0][0]), max(1.0, max_pts[-1][0]), alert, action, False))]
    notes.append("Displacements are relative to the base (first) survey; A is the direction of the A0 groove, B is 90° clockwise from A.")
    if incremental:
        notes.append("Incremental displacements are summed from the bottom of the casing, which is taken as fixed.")
    notes.append("Resultant = √(A² + B²); the alarm uses the largest resultant of the latest survey.")
    values = [("Latest survey", latest, ""), ("Largest resultant displacement", rnd(r_max, 4), "mm"), ("At depth", rnd(z_max, 4), "m"),
              ("Rate over the last interval", rnd(rate, 4), "mm/day"), ("Surveys", len(dates), ""),
              ("Alarm state", STATE_LABEL[state], "")]
    latest_rows = [[rnd(z, 4), rnd(a, 4), rnd(b, 4), rnd(math.hypot(a, b), 4)] for z, a, b in profiles[latest]]
    record["results"] = result(
        summary=[("Largest displacement", rnd(r_max, 4), "mm"), ("At depth", rnd(z_max, 4), "m"), ("Rate per day", rnd(rate, 4), "mm/day")],
        values=values,
        tables=[table("Surveys", ["Date", "Day", "Largest resultant (mm)", "At depth (m)", "Alarm"], list(reversed(survey_rows))),
                table("Latest survey", ["Depth (m)", "Cumulative A (mm)", "Cumulative B (mm)", "Resultant (mm)"], latest_rows)],
        charts=charts, notes=notes,
        method="Probe inclinometer cumulative displacement (ASTM D6230; Dunnicliff 1993)")
    record["summary"] = str(record["results"]["summary"])[:300]
