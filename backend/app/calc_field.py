"""Calculations of the field worksheets (general, survey, geotechnical in-situ tests, geophysics).

Every function takes the cleaned worksheet data (see sheets_field.py) and returns a
:func:`calcbase.result`. Where the company's spreadsheet template differs from the
engineering method, the engineering method is used and a fixed note says so; a few
template behaviours can still be chosen with a select field.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import geo
from .calcbase import CalcError, axis, chart, interpolate, linear_fit, num, result, rnd, series, table, thin
from .seismic import CLASS_NAMES, average_over_30m, classify

KGCM2 = 98.0665  # kPa per kg/cm²
PSF_KPA = 0.45359237 * 9.80665 / 0.3048 ** 2 / 1000  # kPa per lb/ft² (with 30.48 cm per ft)
PSI_KPA = 6.894757  # kPa per lb/in²
G = 9.81

Row = Dict[str, Any]
Value = Tuple[str, Any, str]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _rows(data: Dict[str, Any], key: str) -> List[Row]:
    return [r for r in data.get(key) or [] if isinstance(r, dict)]


def _txt(value: Any) -> str:
    return str(value or "").strip()


def _sum(values: Sequence[Optional[float]]) -> float:
    return sum(v for v in values if v is not None)


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _fx(value: Optional[float], digits: int = 3) -> Optional[str]:
    """Fixed decimals as text, so the result table does not round coordinates and levels."""
    return None if value is None else f"{value:.{digits}f}"


def _dms_angle(deg: float, sec_digits: int = 1) -> str:
    """Angle in degrees as 123° 04' 05.0\"."""
    sign = "-" if deg < 0 else ""
    total = round(abs(deg) * 3600, sec_digits)
    d = int(total // 3600)
    m = int((total - d * 3600) // 60)
    s = total - d * 3600 - m * 60
    return f"{sign}{d}° {m:02d}' {s:0{3 + sec_digits}.{sec_digits}f}\""


def _norm360(a: float) -> float:
    a = math.fmod(a, 360.0)
    return a + 360.0 if a < 0 else a


def _norm180(a: float) -> float:
    a = _norm360(a)
    return a - 360.0 if a > 180.0 else a


def _azimuth(e1: float, n1: float, e2: float, n2: float) -> float:
    if e1 == e2 and n1 == n2:
        raise CalcError("Two control points have the same coordinates")
    return _norm360(math.degrees(math.atan2(e2 - e1, n2 - n1)))


_DMS = re.compile(r"(-?\d+(?:[.,]\d+)?)")


def parse_angle(text: Any, positive: str, negative: str) -> Optional[float]:
    """Decimal degrees from text such as 6°08'02.75"S, 6 8 2.75 LS, -6.134 or 106°53'37" E."""
    if text in (None, ""):
        return None
    value = num(text)
    if value is not None:
        return value
    s = str(text).strip().upper().replace("′", "'").replace("″", '"')
    parts = [float(p.replace(",", ".")) for p in _DMS.findall(s)]
    if not parts or len(parts) > 3:
        raise CalcError("Enter coordinates as degrees, minutes and seconds with N/S or E/W, or as decimal degrees")
    d = abs(parts[0])
    m = parts[1] if len(parts) > 1 else 0.0
    sec = parts[2] if len(parts) > 2 else 0.0
    if m >= 60 or sec >= 60 or m < 0 or sec < 0:
        raise CalcError("Minutes and seconds must be below 60")
    out = d + m / 60 + sec / 3600
    letters = re.sub(r"[^A-Z]", "", s)
    neg_letters = {"S": ("S", "LS"), "W": ("W", "BB")}.get(negative, (negative,))
    if parts[0] < 0 or any(letters.endswith(x) or letters.startswith(x) for x in neg_letters):
        out = -out
    return out


def _coord_values(lat: Optional[float], lon: Optional[float]) -> List[Value]:
    if lat is None or lon is None:
        return []
    try:
        utm = geo.to_utm(lat, lon)
    except ValueError as exc:
        raise CalcError("The coordinates are outside the valid range") from exc
    return [
        ("Latitude", round(lat, 8), "°"), ("Longitude", round(lon, 8), "°"),
        ("Latitude (DMS)", geo.dms(lat, "N", "S"), ""), ("Longitude (DMS)", geo.dms(lon, "E", "W"), ""),
        ("UTM zone", f"{utm['zone']}{utm['hemisphere']}", ""),
        ("Easting", utm["easting"], "m"), ("Northing", utm["northing"], "m"),
    ]


def _consistency_qu(qu_kpa: float) -> str:
    """Consistency of fine-grained soil from the unconfined strength (Terzaghi & Peck)."""
    if qu_kpa < 25:
        return "Very soft"
    if qu_kpa < 50:
        return "Soft"
    if qu_kpa < 100:
        return "Medium stiff"
    if qu_kpa < 200:
        return "Stiff"
    if qu_kpa < 400:
        return "Very stiff"
    return "Hard"


def _pp_table(rows: List[Row], depth_key: str) -> Tuple[List[List[Any]], List[Tuple[float, float]], List[float]]:
    out: List[List[Any]] = []
    pts: List[Tuple[float, float]] = []
    qus: List[float] = []
    for r in rows:
        qu = num(r.get("qu"))
        depth = num(r.get(depth_key))
        if qu is None or depth is None:
            continue
        top = num(r.get("top"))
        mid = (top + depth) / 2 if top is not None and depth_key == "bottom" else depth
        kpa = qu * KGCM2
        over = bool(r.get("over_range"))
        qus.append(kpa)
        pts.append((kpa, mid))
        label = "Above the instrument range" if over else _consistency_qu(kpa)
        out.append(([top] if depth_key == "bottom" else []) + [depth, qu, kpa, kpa / 2, label])
    return out, pts, qus


# --------------------------------------------------------------------------- #
# 01 General
# --------------------------------------------------------------------------- #

def coordinates(data: Dict[str, Any]) -> Dict[str, Any]:
    """01.01 coordinate table: latitude/longitude and UTM in both directions (WGS84)."""
    default_zone = int(num(data.get("zone")) or 0) or None
    default_hemi = _txt(data.get("hemisphere")) or "S"
    rows: List[List[Any]] = []
    plan: Dict[str, List[Tuple[float, float]]] = {}
    total_depth = 0.0
    has_depth = False
    for r in _rows(data, "points"):
        lat, lon = num(r.get("latitude")), num(r.get("longitude"))
        e, n = num(r.get("easting")), num(r.get("northing"))
        zone = int(num(r.get("zone")) or 0) or default_zone
        hemi = _txt(r.get("hemisphere")) or default_hemi
        try:
            if lat is not None and lon is not None:
                utm = geo.to_utm(lat, lon, zone)
                e, n, zone, hemi = utm["easting"], utm["northing"], utm["zone"], utm["hemisphere"]
            elif e is not None and n is not None:
                if zone is None:
                    raise CalcError("Enter the UTM zone for points given as easting and northing")
                if not 100000 <= e <= 900000:
                    raise CalcError("A UTM easting must be between 100000 and 900000 m (six digits)")
                if not 0 <= n <= 10000000:
                    raise CalcError("A UTM northing must be between 0 and 10000000 m")
                ll = geo.from_utm(e, n, zone, hemi)
                lat, lon = ll["latitude"], ll["longitude"]
            else:
                continue
        except ValueError as exc:
            if isinstance(exc, CalcError):
                raise
            raise CalcError("The coordinates are outside the valid range") from exc
        assert lat is not None and lon is not None and e is not None and n is not None
        depth = num(r.get("planned_depth"))
        if depth is not None:
            total_depth += depth
            has_depth = True
        plan.setdefault(f"{zone}{hemi}", []).append((e, n))
        rows.append([_txt(r.get("point")), _fx(lat, 8), _fx(lon, 8), geo.dms(lat, "N", "S"), geo.dms(lon, "E", "W"),
                     f"{zone}{hemi}", _fx(e), _fx(n), _fx(num(r.get("elevation"))), num(r.get("chainage")),
                     depth, _txt(r.get("description"))])
    if not rows:
        raise CalcError("Enter at least one point with latitude/longitude or easting/northing")
    notes = ["Coordinates are converted on the WGS84 ellipsoid with the UTM projection."]
    charts = []
    if len(plan) == 1:
        zone_key = next(iter(plan))
        charts.append(chart("Point plan (UTM)", axis("Easting (m)"), axis("Northing (m)"),
                            series("Points", plan[zone_key], "points")))
    else:
        notes.append("The points lie in more than one UTM zone, so no plan is drawn.")
    values: List[Value] = [("Points", len(rows), "")]
    if has_depth:
        values.append(("Total planned depth", rnd(total_depth, 5), "m"))
    return result(
        summary=[("Points", len(rows), ""), ("Total planned depth", rnd(total_depth, 5) if has_depth else None, "m")],
        values=values,
        tables=[table("Coordinates", ["Point", "Latitude (°)", "Longitude (°)", "Latitude (DMS)", "Longitude (DMS)",
                                      "UTM zone", "Easting (m)", "Northing (m)", "Elevation (m)", "Chainage (m)",
                                      "Planned depth (m)", "Description"], rows,
                      key=["Point", "Easting (m)", "Northing (m)", "Elevation (m)", "Planned depth (m)"])],
        charts=charts, notes=notes, method="WGS84 geographic to UTM conversion")


def work_instruction(data: Dict[str, Any]) -> Dict[str, Any]:
    """01.02 field work instruction: points per rig and per test, planned depth."""
    per_machine: Dict[str, List[float]] = {}
    per_test: Dict[str, int] = {}
    total = 0.0
    count = 0
    for r in _rows(data, "points"):
        if not _txt(r.get("point")):
            continue
        count += 1
        depth = num(r.get("planned_depth")) or 0.0
        total += depth
        m = per_machine.setdefault(_txt(r.get("machine")) or "-", [0.0, 0.0])
        m[0] += 1
        m[1] += depth
        test = _txt(r.get("test")) or "other"
        per_test[test] = per_test.get(test, 0) + 1
    if not count:
        raise CalcError("Enter at least one point")
    test_names = dict(TEST_OPTIONS)
    return result(
        summary=[("Points", count, ""), ("Total planned depth", rnd(total, 5), "m")],
        values=[("Points", count, ""), ("Total planned depth", rnd(total, 5), "m"), ("Rigs / teams", len(per_machine), "")],
        tables=[table("Points per rig", ["Rig / team", "Points", "Planned depth (m)"],
                      [[k, int(v[0]), v[1]] for k, v in per_machine.items()]),
                table("Points per test", ["Test", "Points"], [[test_names.get(k, k), v] for k, v in per_test.items()])],
        method="Totals of the planned points")


def daily_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """01.03 daily report: drilling progress (cumulative = previous + today), manpower, summary."""
    drows: List[List[Any]] = []
    sums = [0.0] * 6  # today depth, cum depth, today spt, cum spt, cum uds, cum ds
    for r in _rows(data, "drilling"):
        name = _txt(r.get("borehole"))
        if not name:
            continue
        plan = num(r.get("plan_depth"))
        prev_d, today_d = num(r.get("prev_depth")) or 0.0, num(r.get("today_depth")) or 0.0
        cum_d = prev_d + today_d
        cum = {k: (num(r.get("prev_" + k)) or 0.0) + (num(r.get("today_" + k)) or 0.0) for k in ("spt", "uds", "ds")}
        today_spt = num(r.get("today_spt")) or 0.0
        progress = cum_d / plan * 100 if plan else None
        drows.append([name, plan, prev_d, today_d, cum_d, rnd(progress, 4), today_spt, cum["spt"], cum["uds"], cum["ds"],
                      _txt(r.get("remarks"))])
        for i, v in enumerate((today_d, cum_d, today_spt, cum["spt"], cum["uds"], cum["ds"])):
            sums[i] += v
    if drows:
        drows.append(["Total", None, None, sums[0], sums[1], None, sums[2], sums[3], sums[4], sums[5], ""])
    manpower = [(_txt(r.get("role")), num(r.get("qty")) or 0.0) for r in _rows(data, "manpower") if _txt(r.get("role"))]
    total_people = sum(q for _, q in manpower)
    srows = []
    for r in _rows(data, "summary"):
        if not _txt(r.get("job")):
            continue
        qty, fin = num(r.get("qty")), num(r.get("finish")) or 0.0
        srows.append([_txt(r.get("job")), qty, fin, dict(UNIT_OPTIONS).get(_txt(r.get("unit")), _txt(r.get("unit"))),
                      rnd(fin / qty * 100, 4) if qty else None])
    if not drows and not manpower and not srows:
        raise CalcError("Enter drilling progress, manpower or the work summary")
    tables = []
    if drows:
        tables.append(table("Drilling progress", ["Borehole", "Plan depth (m)", "Previous depth (m)", "Today (m)",
                                                  "Cumulative depth (m)", "Progress (%)", "SPT today", "SPT cumulative",
                                                  "UDS cumulative", "DS cumulative", "Remarks"], drows,
                            key=["Borehole", "Today (m)", "Cumulative depth (m)", "Progress (%)", "SPT today"]))
    if manpower:
        tables.append(table("Manpower", ["Role", "Persons"], [[k, v] for k, v in manpower] + [["Total", total_people]]))
    if srows:
        tables.append(table("Work summary", ["Work item", "Quantity", "Finished", "Unit", "Progress (%)"], srows))
    values: List[Value] = []
    if drows:
        values += [("Drilled today", rnd(sums[0], 5), "m"), ("Drilled to date", rnd(sums[1], 5), "m"),
                   ("SPT today", sums[2], "")]
    if manpower:
        values.append(("Manpower", total_people, "persons"))
    return result(
        summary=[("Drilled today", rnd(sums[0], 5) if drows else None, "m"),
                 ("Drilled to date", rnd(sums[1], 5) if drows else None, "m"),
                 ("Manpower", total_people if manpower else None, "persons")],
        values=values, tables=tables,
        notes=["Cumulative values are the previous values plus today's values; progress is the cumulative depth over the planned depth."],
        method="Daily progress totals")


LAGGING = [
    ("near_miss", "Near miss"), ("first_aid", "First aid case"), ("mtc", "Medical treatment case (MTC)"),
    ("rwdc", "Restricted work day case (RWDC)"), ("lwdc", "Lost work day case (LWDC)"), ("fatality", "Fatality"),
    ("vehicle", "Motor vehicle accident"), ("property", "Property damage"), ("environment", "Environmental damage"),
    ("illness", "Occupational illness"),
]


def hse_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """01.04 daily HSE report: man-hours, indicators, LTIFR and TRIR."""
    mrows: List[List[Any]] = []
    today = 0.0
    for r in _rows(data, "manhours"):
        if not _txt(r.get("position")):
            continue
        nw = (num(r.get("nw_manpower")) or 0.0) * (num(r.get("nw_hours")) or 0.0)
        ot = (num(r.get("ot_manpower")) or 0.0) * (num(r.get("ot_hours")) or 0.0)
        today += nw + ot
        mrows.append([_txt(r.get("position")), num(r.get("nw_manpower")), num(r.get("nw_hours")), nw,
                      num(r.get("ot_manpower")), num(r.get("ot_hours")), ot, nw + ot])
    monthly = [(_txt(r.get("month")), num(r.get("manhours")) or 0.0) for r in _rows(data, "monthly") if _txt(r.get("month"))]
    previous = num(data.get("previous_manhours"))
    notes = []
    if previous is not None:
        project = previous + today
        notes.append("Project man-hours are the man-hours before today plus today's man-hours.")
    elif monthly:
        project = sum(v for _, v in monthly)
        notes.append("Project man-hours are the sum of the monthly man-hours, which include today.")
    else:
        project = today
        notes.append("Enter the man-hours before today or the monthly man-hours to get the project total.")

    def cum(key: str) -> Tuple[float, float, float]:
        t = p = 0.0
        for r in _rows(data, "lagging"):
            if r.get("item") == key:
                t += num(r.get("today")) or 0.0
                p += num(r.get("previous")) or 0.0
        return t, p, t + p

    lag_names = dict(LAGGING)
    stats: List[List[Any]] = []
    for group, key in (("Leading", "leading"), ("Lagging", "lagging")):
        for r in _rows(data, key):
            name = lag_names.get(_txt(r.get("item")), _txt(r.get("item"))) if key == "lagging" else _txt(r.get("item"))
            if not name:
                continue
            t, p = num(r.get("today")) or 0.0, num(r.get("previous")) or 0.0
            stats.append([group, name, t, p, t + p, _txt(r.get("remark"))])
    lti = cum("lwdc")[2] + cum("fatality")[2]
    trc = lti + cum("rwdc")[2] + cum("mtc")[2]
    base = num(data.get("rate_base")) or 200000.0
    template = data.get("trir_basis") == "template"
    ltifr = lti * base / project if project > 0 else None
    trir = ((lti + trc) if template else trc) * base / project if project > 0 else None
    notes.append("LTI = lost work day cases + fatalities; recordable cases = LTI + restricted work day cases + medical treatment cases.")
    notes.append("LTIFR = LTI × rate base / project man-hours; TRIR = recordable cases × rate base / project man-hours.")
    if template:
        notes.append("TRIR follows the template, which counts lost time injuries twice; use the recordable-case basis for reporting.")
    if project <= 0:
        notes.append("The rates need project man-hours above zero.")
    tables = []
    if mrows:
        mrows.append(["Total", None, None, _sum([r[3] for r in mrows]), None, None, _sum([r[6] for r in mrows]), today])
        tables.append(table("Man-hours today", ["Position", "Normal manpower", "Normal hours", "Normal man-hours",
                                                "Overtime manpower", "Overtime hours", "Overtime man-hours", "Total man-hours"], mrows))
    if monthly:
        tables.append(table("Monthly man-hours", ["Month", "Man-hours"], [[m, v] for m, v in monthly] + [["Total", sum(v for _, v in monthly)]]))
    if stats:
        tables.append(table("HSE statistics", ["Indicator", "Item", "Today", "Previous", "Cumulative", "Remark"], stats))
    return result(
        summary=[("Man-hours today", rnd(today, 6), "h"), ("Project man-hours", rnd(project, 7), "h"),
                 ("LTIFR", rnd(ltifr, 3), ""), ("TRIR", rnd(trir, 3), "")],
        values=[("Man-hours today", rnd(today, 6), "h"), ("Project man-hours", rnd(project, 7), "h"),
                ("Lost time injuries (LTI)", lti, ""), ("Recordable cases", trc, ""), ("Rate base", base, "h"),
                ("LTIFR", rnd(ltifr, 3), ""), ("TRIR", rnd(trir, 3), "")],
        tables=tables, notes=notes, method="Frequency rates per rate base of man-hours")


# --------------------------------------------------------------------------- #
# 02 Survey
# --------------------------------------------------------------------------- #

def gps_point(data: Dict[str, Any]) -> Dict[str, Any]:
    """02.01 GNSS point description: approximate position to decimal degrees and UTM."""
    lat = parse_angle(data.get("latitude"), "N", "S")
    lon = parse_angle(data.get("longitude"), "E", "W")
    values = _coord_values(lat, lon)
    h = num(data.get("ellipsoid_height"))
    if h is not None:
        values.append(("Ellipsoid height", h, "m"))
    if not values:
        return result(notes=["Enter the approximate latitude and longitude to convert them."], method="Point description")
    return result(summary=[("Latitude", values[0][1] if lat is not None else None, "°"),
                           ("Longitude", values[1][1] if lon is not None else None, "°")],
                  values=values, notes=["The approximate position is converted on WGS84; the final coordinates come from the GNSS processing."],
                  method="Point description")


def _local_dt(day: Any, clock: Any) -> Optional[datetime]:
    if not day or not clock:
        return None
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*$", str(clock))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise CalcError("Enter the time as HH:MM")
    try:
        d = date.fromisoformat(str(day))
    except ValueError as exc:
        raise CalcError("Enter the date as YYYY-MM-DD") from exc
    return datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def gps_logsheet(data: Dict[str, Any]) -> Dict[str, Any]:
    """02.01 GNSS observation logsheet: UTC times, day of year, session length."""
    offset = num(data.get("utc_offset"))
    offset = 7.0 if offset is None else offset
    start = _local_dt(data.get("start_date"), data.get("start_time"))
    end = _local_dt(data.get("end_date") or data.get("start_date"), data.get("end_time"))
    values: List[Value] = []
    notes = []
    duration = None
    if start:
        su = start - timedelta(hours=offset)
        values += [("Start (UTC)", su.strftime("%Y-%m-%d %H:%M"), ""), ("Day of year (UTC)", su.timetuple().tm_yday, "")]
    if end:
        eu = end - timedelta(hours=offset)
        values += [("End (UTC)", eu.strftime("%Y-%m-%d %H:%M"), ""), ("Day of year at the end (UTC)", eu.timetuple().tm_yday, "")]
    if start and end:
        duration = (end - start).total_seconds() / 3600
        if duration <= 0:
            raise CalcError("The session must end after it starts")
        values.append(("Session duration", rnd(duration, 4), "h"))
    hb, ha = num(data.get("antenna_height_before")), num(data.get("antenna_height_after"))
    if hb is not None and ha is not None:
        diff = (ha - hb) * 1000
        values.append(("Antenna height difference", rnd(diff, 3) if diff else 0.0, "mm"))
        if abs(diff) > 2:
            notes.append("The antenna height before and after the session differs by more than two millimetres; check the measurement.")
    lat = parse_angle(data.get("latitude"), "N", "S")
    lon = parse_angle(data.get("longitude"), "E", "W")
    values += _coord_values(lat, lon)
    if not values:
        raise CalcError("Enter the session start and end or the approximate position")
    notes.append("UTC = local time − UTC offset; the day of year is counted from the UTC date.")
    return result(summary=[("Session duration", rnd(duration, 4) if duration is not None else None, "h")],
                  values=values, notes=notes, method="GNSS static session log")


def topographic(data: Dict[str, Any]) -> Dict[str, Any]:
    """02.02 topographic detail points: statistics and a plan by feature code."""
    pts = []
    for r in _rows(data, "points"):
        e, n = num(r.get("easting")), num(r.get("northing"))
        if e is None or n is None:
            continue
        pts.append((_txt(r.get("point")), e, n, num(r.get("elevation")), _txt(r.get("code")) or "-"))
    if not pts:
        raise CalcError("Enter at least one point with easting and northing")
    es, ns = [p[1] for p in pts], [p[2] for p in pts]
    zs = [p[3] for p in pts if p[3] is not None]
    codes: Dict[str, List[Tuple[float, float]]] = {}
    for p in pts:
        codes.setdefault(p[4], []).append((p[1], p[2]))
    ranked = sorted(codes.items(), key=lambda kv: -len(kv[1]))
    shown = ranked[:7]
    rest = [xy for _, xys in ranked[7:] for xy in xys]
    plan_series = [series(code, xys, "points") for code, xys in shown]
    if rest:
        plan_series.append(series("Other codes", rest, "points"))
    values: List[Value] = [("Points", len(pts), ""), ("Easting range", rnd(max(es) - min(es), 5), "m"),
                           ("Northing range", rnd(max(ns) - min(ns), 5), "m")]
    if zs:
        values += [("Lowest elevation", min(zs), "m"), ("Highest elevation", max(zs), "m")]
    dup = len(pts) - len({p[0] for p in pts if p[0]}) - sum(1 for p in pts if not p[0])
    notes = []
    if dup > 0:
        notes.append("Some point numbers are used more than once; check the list.")
    return result(
        summary=[("Points", len(pts), ""), ("Lowest elevation", min(zs) if zs else None, "m"),
                 ("Highest elevation", max(zs) if zs else None, "m")],
        values=values,
        tables=[table("Points per feature code", ["Code", "Points"], [[c, len(x)] for c, x in ranked])],
        charts=[chart("Detail point plan", axis("Easting (m)"), axis("Northing (m)"), *plan_series)],
        notes=notes, method="Detail point list")


def _angle(r: Row) -> Optional[float]:
    d, m, s = num(r.get("angle_d")), num(r.get("angle_m")), num(r.get("angle_s"))
    if d is None and m is None and s is None:
        return None
    return (d or 0.0) + (m or 0.0) / 60 + (s or 0.0) / 3600


def traverse(data: Dict[str, Any]) -> Dict[str, Any]:
    """02.02 traverse (polygon): angular closure on azimuths, Bowditch (compass rule) adjustment."""
    def p(key: str, label: str) -> float:
        v = num(data.get(key))
        if v is None:
            raise CalcError(f"{label} is required")
        return v

    closed = data.get("traverse_type") == "closed"
    sign = -1.0 if data.get("angle_direction") == "left" else 1.0
    ref_e, ref_n = p("start_ref_e", "Backsight reference easting"), p("start_ref_n", "Backsight reference northing")
    e0, n0 = p("start_e", "Start station easting"), p("start_n", "Start station northing")
    a0 = _azimuth(ref_e, ref_n, e0, n0)
    if closed:
        e_end, n_end, a_end = e0, n0, _norm360(a0 + 180)
    else:
        e_end, n_end = p("end_e", "End station easting"), p("end_n", "End station northing")
        a_end = _azimuth(e_end, n_end, p("end_ref_e", "Foresight reference easting"), p("end_ref_n", "Foresight reference northing"))
    rows = [r for r in _rows(data, "stations") if _angle(r) is not None or num(r.get("distance")) is not None]
    if not rows:
        raise CalcError("Enter the stations with their angles and distances")
    angles = [a for a in (_angle(r) for r in rows) if a is not None]
    n = len(angles)
    if n < 2:
        raise CalcError("Enter at least two measured angles")
    # Azimuth closure: carry the start azimuth through all angles and compare with the closing azimuth.
    carried = a0 + sum(sign * b - sign * 180.0 for b in angles)
    f_ang = _norm180(carried - a_end) * 3600  # seconds
    corr = -sign * f_ang / n  # correction to each measured angle (seconds)
    factor = num(data.get("angle_factor"))
    factor = 10.0 if factor is None else factor
    tol = factor * math.sqrt(n)
    # Legs with adjusted azimuths.
    az = a0
    legs: List[Dict[str, Any]] = []
    stations: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        beta = _angle(r)
        st: Dict[str, Any] = {"name": _txt(r.get("station")), "beta": beta, "beta_adj": None, "az": None, "d": None}
        if beta is not None:
            beta_adj = beta + corr / 3600
            az = _norm360(az + sign * beta_adj - sign * 180.0)
            st["beta_adj"] = beta_adj
        d = num(r.get("distance"))
        if d is not None:
            if beta is None and i > 0:
                raise CalcError("Each station with a distance needs a measured angle")
            if d <= 0:
                raise CalcError("Distances must be greater than zero")
            st["az"], st["d"] = az, d
            legs.append(st)
        stations.append(st)
    if not legs:
        raise CalcError("Enter the distances between the stations")
    total = sum(leg["d"] for leg in legs)
    de = [leg["d"] * math.sin(math.radians(leg["az"])) for leg in legs]
    dn = [leg["d"] * math.cos(math.radians(leg["az"])) for leg in legs]
    f_e = sum(de) - (e_end - e0)
    f_n = sum(dn) - (n_end - n0)
    f_l = math.hypot(f_e, f_n)
    precision = total / f_l if f_l > 1e-9 else None
    required = num(data.get("required_precision")) or 6000.0
    out_rows: List[List[Any]] = []
    e, nn = e0, n0
    plan = [(e0, n0)]
    k = 0
    for st in stations:
        row: List[Any] = [st["name"], _dms_angle(st["beta"]) if st["beta"] is not None else "",
                          rnd(corr, 3) if st["beta"] is not None else None,
                          _dms_angle(_norm360(st["beta_adj"])) if st["beta_adj"] is not None else "",
                          _dms_angle(st["az"]) if st["az"] is not None else ""]
        coords = [_fx(e), _fx(nn)]
        if st["d"] is not None:
            ce, cn = -f_e * st["d"] / total, -f_n * st["d"] / total
            row += [_fx(st["d"]), _fx(de[k]), _fx(ce, 4), _fx(dn[k]), _fx(cn, 4)]
            e += de[k] + ce
            nn += dn[k] + cn
            k += 1
            plan.append((e, nn))
        else:
            row += [None, None, None, None, None]
        out_rows.append(row + coords)
    ang_ok = abs(f_ang) <= tol
    lin_ok = precision is None or precision >= required
    notes = [
        "Angular misclosure = start azimuth + Σ angles ∓ n·180° − closing azimuth; it is spread equally over the angles.",
        "Linear misclosure = √(fE² + fN²); fE and fN are spread in proportion to the leg lengths (Bowditch / compass rule).",
        "For a closed loop the last row is the start station again, with the angle that closes on the backsight reference.",
    ]
    ctrl = [(ref_e, ref_n), (e0, n0)] + ([] if closed else [(e_end, n_end)])
    return result(
        summary=[("Angular misclosure", round(f_ang, 1), "″"), ("Linear misclosure", round(f_l, 4), "m"),
                 ("Precision (1 : X)", round(precision) if precision else None, "")],
        values=[("Angles", n, ""), ("Start azimuth", _dms_angle(a0), ""), ("Closing azimuth", _dms_angle(a_end), ""),
                ("Angular misclosure", round(f_ang, 1), "″"), ("Angular tolerance", rnd(tol, 3), "″"),
                ("Angular check", "Within tolerance" if ang_ok else "Exceeds tolerance", ""),
                ("Misclosure in easting fE", round(f_e, 4), "m"), ("Misclosure in northing fN", round(f_n, 4), "m"),
                ("Linear misclosure", round(f_l, 4), "m"), ("Total distance", rnd(total, 6), "m"),
                ("Precision (1 : X)", round(precision) if precision else None, ""), ("Required precision (1 : X)", required, ""),
                ("Linear check", "Within tolerance" if lin_ok else "Exceeds tolerance", "")],
        tables=[table("Adjusted traverse", ["Station", "Measured angle", "Angle correction (″)", "Adjusted angle", "Azimuth",
                                            "Distance (m)", "ΔE (m)", "Correction E (m)", "ΔN (m)", "Correction N (m)",
                                            "Easting (m)", "Northing (m)"], out_rows)],
        charts=[chart("Traverse plan", axis("Easting (m)"), axis("Northing (m)"),
                      series("Adjusted traverse", plan, "both"), series("Control points", ctrl, "points"))],
        notes=notes, method="Azimuth closure and Bowditch (compass rule) adjustment")


def levelling(data: Dict[str, Any]) -> Dict[str, Any]:
    """02.02 levelling: rise and fall reduction, misclosure against c√K, proportional adjustment."""
    start = num(data.get("start_elevation"))
    if start is None:
        raise CalcError("Start benchmark elevation is required")
    rows = [r for r in _rows(data, "readings")
            if any(num(r.get(k)) is not None for k in ("bs", "is_reading", "fs"))]
    if len(rows) < 2:
        raise CalcError("Enter at least two rows of readings")
    if num(rows[0].get("bs")) is None:
        raise CalcError("The first row must have a backsight on the start benchmark")
    prev = float(rows[0]["bs"])
    rl = start
    setup = 1
    pts: List[Dict[str, Any]] = [{"name": _txt(rows[0].get("point")), "bs": prev, "is": None, "fs": None,
                                  "rise": None, "fall": None, "rl": rl, "setup": 0, "dist": 0.0}]
    cum_d = 0.0
    has_dist = True
    for r in rows[1:]:
        bs, is_, fs = num(r.get("bs")), num(r.get("is_reading")), num(r.get("fs"))
        cur = fs if fs is not None else is_
        if cur is None:
            raise CalcError("Each row after the first needs an intermediate sight or a foresight")
        diff = prev - cur
        rl += diff
        d = num(r.get("distance"))
        if d is None:
            has_dist = False
        else:
            cum_d += d
        pts.append({"name": _txt(r.get("point")), "bs": bs, "is": is_ if fs is None else None, "fs": fs,
                    "rise": diff if diff > 0 else None, "fall": -diff if diff < 0 else None,
                    "rl": rl, "setup": setup, "dist": cum_d})
        if bs is not None:
            if fs is None:
                raise CalcError("A row with a new backsight must also have the foresight of the change point")
            prev = bs
            setup += 1
        else:
            prev = cur
    if num(rows[-1].get("fs")) is None:
        raise CalcError("The last row must be a foresight")
    s_bs = _sum([p["bs"] for p in pts])
    s_fs = _sum([p["fs"] for p in pts])
    s_rise = _sum([p["rise"] for p in pts])
    s_fall = _sum([p["fall"] for p in pts])
    closure = data.get("closure") or "loop"
    end_known = start if closure == "loop" else num(data.get("end_elevation"))
    if closure == "link" and end_known is None:
        raise CalcError("Closing benchmark elevation is required for a levelling line between two benchmarks")
    misclose = rl - end_known if end_known is not None and closure != "open" else None
    total_km = cum_d / 1000 if has_dist and cum_d > 0 else None
    c = num(data.get("allowable_factor"))
    c = 8.0 if c is None else c
    allowable = c * math.sqrt(total_km) if total_km is not None else None
    setups = setup
    out_rows: List[List[Any]] = []
    profile = []
    for i, p_ in enumerate(pts):
        corr = None
        if misclose is not None:
            frac = (p_["dist"] / cum_d) if has_dist and cum_d > 0 else (p_["setup"] / setups if setups else 0.0)
            corr = -misclose * frac
        adj = p_["rl"] + (corr or 0.0)
        out_rows.append([p_["name"], _fx(p_["bs"]), _fx(p_["is"]), _fx(p_["fs"]), _fx(p_["rise"]), _fx(p_["fall"]),
                         _fx(p_["rl"]), _fx(corr, 4), _fx(adj)])
        profile.append((p_["dist"] if has_dist else float(i), adj))
    notes = ["Rise and fall method: ΣBS − ΣFS = ΣRise − ΣFall = last RL − first RL (arithmetic check)."]
    if misclose is not None:
        notes.append("The misclosure is distributed in proportion to the cumulative distance (or to the number of set-ups when distances are missing).")
    if allowable is None and misclose is not None:
        notes.append("Enter the distances to compare the misclosure with the allowable c√K.")
    arith_ok = abs((s_bs - s_fs) - (s_rise - s_fall)) < 1e-6 and abs((s_bs - s_fs) - (rl - start)) < 1e-6
    values: List[Value] = [
        ("ΣBS", round(s_bs, 4), "m"), ("ΣFS", round(s_fs, 4), "m"), ("ΣRise", round(s_rise, 4), "m"),
        ("ΣFall", round(s_fall, 4), "m"), ("Arithmetic check", "Correct" if arith_ok else "Error", ""),
        ("Last reduced level", round(rl, 4), "m"), ("Set-ups", setups, ""),
    ]
    if total_km is not None:
        values.append(("Levelling distance", rnd(total_km, 4), "km"))
    if misclose is not None:
        values.append(("Misclosure", round(misclose * 1000, 2), "mm"))
    if allowable is not None:
        values.append(("Allowable misclosure", rnd(allowable, 3), "mm"))
        values.append(("Closure check", "Within tolerance" if misclose is not None and abs(misclose * 1000) <= allowable else "Exceeds tolerance", ""))
    return result(
        summary=[("Misclosure", round(misclose * 1000, 2) if misclose is not None else None, "mm"),
                 ("Allowable misclosure", rnd(allowable, 3), "mm")],
        values=values,
        tables=[table("Level book (rise and fall)", ["Point", "BS (m)", "IS (m)", "FS (m)", "Rise (m)", "Fall (m)",
                                                     "Reduced level (m)", "Correction (m)", "Adjusted level (m)"], out_rows)],
        charts=[chart("Levelling profile", axis("Cumulative distance (m)" if has_dist else "Point number"),
                      axis("Adjusted level (m)"), series("Adjusted level", profile, "both"))],
        notes=notes, method="Rise and fall reduction with proportional misclosure adjustment")


def benchmark(data: Dict[str, Any]) -> Dict[str, Any]:
    """02.03 benchmark description: distances, azimuths and height differences between the benchmarks."""
    bms = [(_txt(r.get("bm_id")) or f"#{i + 1}", num(r.get("easting")), num(r.get("northing")), num(r.get("elevation")))
           for i, r in enumerate(_rows(data, "benchmarks"))]
    bms = [b for b in bms if b[1] is not None and b[2] is not None]
    if len(bms) < 2:
        raise CalcError("Enter at least two benchmarks with coordinates")
    rows: List[List[Any]] = []
    for i in range(len(bms)):
        for j in range(i + 1, len(bms)):
            a, b = bms[i], bms[j]
            assert a[1] is not None and a[2] is not None and b[1] is not None and b[2] is not None
            dist = math.hypot(b[1] - a[1], b[2] - a[2])
            az = _dms_angle(_azimuth(a[1], a[2], b[1], b[2]), 0) if dist > 0 else ""
            dh = b[3] - a[3] if a[3] is not None and b[3] is not None else None
            rows.append([a[0], b[0], _fx(dist), az, _fx(dh)])
    return result(summary=[("Benchmarks", len(bms), "")], values=[("Benchmarks", len(bms), "")],
                  tables=[table("Between benchmarks", ["From", "To", "Horizontal distance (m)", "Azimuth", "Height difference (m)"], rows)],
                  charts=[chart("Benchmark plan", axis("Easting (m)"), axis("Northing (m)"),
                                series("Benchmarks", [(b[1], b[2]) for b in bms], "points"))],
                  method="Grid distances and height differences")


# --------------------------------------------------------------------------- #
# 03 Geotechnical
# --------------------------------------------------------------------------- #

def pocket_penetrometer(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.01 pocket penetrometer (borehole qu): kPa, su ≈ qu/2 and consistency."""
    rows, pts, qus = _pp_table(_rows(data, "readings"), "bottom")
    if not rows:
        raise CalcError("Enter the readings with depth and qu")
    return result(
        summary=[("Readings", len(rows), ""), ("Mean qu", rnd(_mean(qus), 3), "kPa")],
        values=[("Readings", len(rows), ""), ("Minimum qu", rnd(min(qus), 3), "kPa"), ("Maximum qu", rnd(max(qus), 3), "kPa"),
                ("Mean qu", rnd(_mean(qus), 3), "kPa")],
        tables=[table("Pocket penetrometer", ["From (m)", "To (m)", "qu (kg/cm²)", "qu (kPa)", "su ≈ qu/2 (kPa)", "Consistency"], rows)],
        charts=[chart("Pocket penetrometer qu", axis("qu (kPa)"), axis("Depth (m)", reverse=True), series("qu", pts, "both"))],
        notes=["The pocket penetrometer gives an index of the unconfined strength; su ≈ qu/2 is an estimate only.",
               "Consistency classes after Terzaghi and Peck from qu."],
        method="Pocket penetrometer index")


def _spt_gamma(n: float) -> float:
    """Unit weight (kN/m³) estimated from the field N (template table)."""
    for limit, gamma in ((3, 14.0), (5, 14.5), (10, 15.0), (18, 16.0), (26, 17.0), (40, 18.0)):
        if n < limit:
            return gamma
    return 19.0


def _cb(diameter: Optional[float]) -> float:
    """Borehole diameter correction (Skempton 1986, as tabled by Youd et al. 2001): 65–115 mm 1.00,
    150 mm 1.05, 200 mm 1.15. The sources give only these points; between them the factor is
    interpolated linearly so there is no step at 115/116 mm. Holes under 65 mm are outside the table
    and take 1.00 (a small hole does not relieve the soil around the sampler)."""
    if diameter is None or diameter <= 115:
        return 1.0
    if diameter <= 150:
        return round(1.0 + 0.05 * (diameter - 115) / 35, 4)
    if diameter < 200:
        return round(1.05 + 0.10 * (diameter - 150) / 50, 4)
    return 1.15


DEFAULT_STICK_UP = 1.5  # m of rod above the ground when not recorded (Idriss & Boulanger 2010)


def _cr(rod: float) -> float:
    """Rod length correction, Youd et al. (2001) Table 2: < 3 m 0.75, 3–4 m 0.80, 4–6 m 0.85, 6–10 m 0.95,
    10–30 m 1.00. Rod length = test depth + stick-up. No published value above 30 m: 1.00."""
    if rod < 3:
        return 0.75
    if rod < 4:
        return 0.80
    if rod < 6:
        return 0.85
    if rod < 10:
        return 0.95
    return 1.0


def _density_class(n: float, coarse: bool) -> str:
    if coarse:
        return "Very loose to loose" if n < 10 else "Medium dense" if n < 30 else "Dense" if n < 50 else "Very dense"
    return ("Very soft to soft" if n < 4 else "Medium stiff" if n < 8 else "Stiff" if n < 15
            else "Very stiff" if n < 30 else "Hard")


def _coarse(row: Row) -> bool:
    soil = _txt(row.get("soil")).lower()
    if soil:
        return soil in ("sand", "coarse", "gravel")
    uscs = _txt(row.get("uscs")).upper()
    return uscs.startswith(("S", "G"))


def spt_correction(header: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """SPT N to N60 and (N1)60.

    header: energy_ratio (%), borehole_diameter (mm), sampler ("standard" | "no_liner"),
    stick_up (m, rod above ground), groundwater (m below ground, blank = none), gamma_w (kN/m³),
    cn_method ("liao_whitman" | "template").
    rows: depth (m); n or blows (blows for the 300 mm test drive, or the blows reached at refusal);
    penetration_cm (cm, default 30) or penetration_mm; soil ("sand" | "clay") or uscs; optional
    unit_weight (kN/m³) and layer.
    """
    er = num(header.get("energy_ratio"))
    er = 60.0 if er is None else er
    if er <= 0:
        raise CalcError("The hammer energy ratio must be greater than zero")
    ce = er / 60
    cb = _cb(num(header.get("borehole_diameter")))
    cs = 1.2 if _txt(header.get("sampler")).lower() in ("no_liner", "non-standard", "non_standard") else 1.0
    diameter = num(header.get("borehole_diameter"))
    stick = num(header.get("stick_up"))
    stick_default = stick is None
    if stick is None:
        stick = DEFAULT_STICK_UP
    gw = num(header.get("groundwater"))
    gamma_w = num(header.get("gamma_w")) or 9.81
    template = header.get("cn_method") == "template"
    high_stress = 0.0
    tests = []
    for r in rows:
        depth = num(r.get("depth"))
        blows = num(r.get("n")) if num(r.get("n")) is not None else num(r.get("blows"))
        if depth is None or blows is None:
            continue
        pen = num(r.get("penetration_cm"))
        if pen is None and num(r.get("penetration_mm")) is not None:
            pen = float(r["penetration_mm"]) / 10
        if pen is None:
            pen = 30.0
        if pen <= 0:
            raise CalcError("The penetration must be greater than zero")
        tests.append((depth, blows, min(pen, 30.0), r))
    if not tests:
        raise CalcError("Enter the SPT depths and blow counts")
    tests.sort(key=lambda t: t[0])
    sv = 0.0
    last = 0.0
    out_rows: List[List[Any]] = []
    prof: Dict[str, List[Tuple[float, float]]] = {"N": [], "N60": [], "N corrected": []}
    n_refusal = 0
    for depth, blows, pen, r in tests:
        n = blows * 30 / pen  # extrapolated to 300 mm at refusal
        refusal = pen < 30
        n_refusal += refusal
        gamma = num(r.get("unit_weight")) or _spt_gamma(n)
        sv += (depth - last) * gamma
        last = depth
        u = gamma_w * max(0.0, depth - gw) if gw is not None else 0.0
        sv_eff = sv - u
        coarse = _coarse(r)
        cn: Optional[float] = None
        if sv_eff > 0:
            if template:
                cn = min(1.7, max(0.577, (100 / sv_eff) ** (0.65 if coarse else 1.0)))
            elif coarse:
                cn = min(1.7, math.sqrt(100 / sv_eff))
        cr = _cr(depth + stick)
        if coarse and sv_eff > 200:
            high_stress = max(high_stress, sv_eff)
        n60 = n * ce * cb * cs * cr
        n160 = n60 * cn if coarse and cn is not None else None
        ncorr = n160 if coarse else n60
        out_rows.append([depth, blows, pen, rnd(n, 5), "Refusal" if refusal else "", "Sand" if coarse else "Clay", gamma,
                         round(sv, 2), round(u, 2), round(sv_eff, 2), rnd(cn, 4), round(ce, 4), cb, cs, cr,
                         round(n60, 3), round(n160, 3) if n160 is not None else None,
                         round(ncorr, 3) if ncorr is not None else None,
                         _density_class(ncorr, coarse) if ncorr is not None else ""])
        prof["N"].append((n, depth))
        prof["N60"].append((n60, depth))
        if ncorr is not None:
            prof["N corrected"].append((ncorr, depth))
    notes = [
        "N60 = N × CE × CB × CS × CR with CE = ER / 60; (N1)60 = N60 × CN for sand; N corrected is N60 for clay and (N1)60 for sand.",
        "CB after Skempton (1986) / Youd et al. (2001): 1.00 up to 115 mm, 1.05 at 150 mm, 1.15 from 200 mm, interpolated between; CR by rod length (depth + stick-up) after Youd et al. (2001): < 3 m 0.75, 3–4 m 0.80, 4–6 m 0.85, 6–10 m 0.95, 10–30 m 1.00.",
        "CE, CB, CS and CR are applied in every soil to give N60; CN only in sand. EN ISO 22476-3 gives the rod length factor for sands, with 0.75 for 3–4 m.",
        "Unit weight is taken from the row or estimated from N; total stress is summed from the ground surface and pore pressure is hydrostatic below the groundwater level.",
        "Classes from N corrected: sand very loose to loose, medium dense, dense, very dense; clay very soft to soft, medium stiff, stiff, very stiff, hard.",
    ]
    if template:
        notes.append("CN follows the template: (100/σ'v) to the power 0.65 for sand and 1 for clay, limited to 0.577–1.7.")
    else:
        notes.append("CN = (Pa/σ'v)^0.5 ≤ 1.7 (Liao and Whitman 1986), applied to sand only.")
    if n_refusal:
        notes.append("At refusal N is extrapolated to 300 mm of penetration; treat these values with care.")
    if stick_default:
        notes.append("Stick-up not recorded: 1.5 m of rod above the ground is assumed for the rod length (Idriss and Boulanger 2010).")
    if diameter is not None and diameter < 65:
        notes.append("Borehole diameter below the 65–115 mm range of the standard test; CB = 1.00 is used. Note it in the log.")
    if last + stick > 30:
        notes.append("Rods longer than 30 m: CR = 1.00 is used; very long rods may lose some energy, which only a measured energy ratio captures.")
    if high_stress and not template:
        notes.append("σ'v above 200 kPa in sand: CN is uncertain at such stresses, and Youd et al. (2001) advise against the equation above 300 kPa.")
    return result(
        summary=[("Tests", len(out_rows), ""), ("CE", round(ce, 4), ""), ("Refusals", n_refusal or None, "")],
        values=[("Tests", len(out_rows), ""), ("Energy ratio", er, "%"), ("CE", round(ce, 4), ""), ("CB", cb, ""),
                ("CS", cs, ""), ("Refusals", n_refusal, "")],
        tables=[table("SPT corrections", ["Depth (m)", "Blows", "Penetration (cm)", "N (300 mm)", "Remark", "Soil",
                                          "γ (kN/m³)", "σv (kPa)", "u (kPa)", "σ'v (kPa)", "CN", "CE", "CB", "CS", "CR",
                                          "N60", "(N1)60", "N corrected", "Consistency / density"], out_rows,
                      key=["Depth (m)", "N (300 mm)", "N60", "N corrected", "Consistency / density"], note="Remark")],
        charts=[chart("SPT N values", axis("N"), axis("Depth (m)", reverse=True),
                      series("N", prof["N"]), series("N60", prof["N60"]), series("N corrected", prof["N corrected"]))],
        notes=notes, method="SPT energy and overburden corrections (Skempton 1986; Youd et al. 2001)")


def spt_corrected(data: Dict[str, Any]) -> Dict[str, Any]:
    return spt_correction(data, _rows(data, "tests"))


VANE_CONSTANTS = {"2": 5.17, "2.5": 2.59, "3.625": 0.905}  # psf per lb·in, supplier table
VANE_DIAMETER_IN = {"2": 2.0, "2.5": 2.5, "3.625": 3.625}


def fvst(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.02 field vane shear test: su peak and remoulded, sensitivity, Bjerrum correction."""
    a = num(data.get("calib_a"))
    if a is None:
        raise CalcError("Calibration slope a is required")
    b = num(data.get("calib_b")) or 0.0
    arm = num(data.get("torque_arm")) or num(data.get("torque_arm_in")) or 12.0
    size = _txt(data.get("vane_size")) or "2.5"
    if size == "custom":
        d_mm, h_mm = num(data.get("vane_diameter_mm")), num(data.get("vane_height_mm"))
        if not d_mm or not h_mm:
            raise CalcError("Enter the vane diameter and height")
        d_in, h_in = d_mm / 25.4, h_mm / 25.4
        k = 144 / (math.pi * d_in ** 2 * (h_in / 2 + d_in / 6))  # psf per lb·in, both ends shearing
    elif size in VANE_CONSTANTS:
        k = VANE_CONSTANTS[size]
    else:
        raise CalcError("Choose the vane size")
    rows = _rows(data, "readings")
    uc = [v for v in (num(r.get("dial_uc")) for r in rows) if v is not None]
    rc = [v for v in (num(r.get("dial_rc")) for r in rows) if v is not None]
    sh = [v for v in (num(r.get("dial_shaft")) for r in rows) if v is not None]
    if not uc:
        raise CalcError("Enter the dial readings of the undisturbed test")
    shaft_dial = max(sh) if sh else 0.0
    f_sh = a * shaft_dial + b if shaft_dial > 0 else 0.0

    def strength(dials: List[float]) -> Optional[Dict[str, float]]:
        if not dials:
            return None
        f = a * max(dials) + b
        torque = max(0.0, f - f_sh) * arm
        psf = k * torque
        return {"f": f, "t": torque, "psf": psf, "kgcm2": psf * PSF_KPA / KGCM2, "kpa": psf * PSF_KPA}

    peak, rem = strength(uc), strength(rc)
    assert peak is not None
    pi = num(data.get("plasticity_index"))
    mu = min(1.0, 1.7 - 0.54 * math.log10(pi)) if pi is not None and pi > 0 else None
    st = peak["kpa"] / rem["kpa"] if rem and rem["kpa"] > 0 else None
    values: List[Value] = [
        ("Vane constant K", rnd(k, 4), "psf/(lb·in)"), ("Peak force", round(peak["f"], 3), "lb"),
        ("Shaft friction force", round(f_sh, 3), "lb"), ("Peak torque", round(peak["t"], 3), "lb·in"),
        ("su peak", round(peak["psf"], 2), "psf"), ("su peak", round(peak["kgcm2"], 4), "kg/cm²"),
        ("su peak", round(peak["kpa"], 2), "kPa"),
    ]
    if rem:
        values += [("Remoulded force", round(rem["f"], 3), "lb"), ("Remoulded torque", round(rem["t"], 3), "lb·in"),
                   ("su remoulded", round(rem["psf"], 2), "psf"), ("su remoulded", round(rem["kgcm2"], 4), "kg/cm²"),
                   ("su remoulded", round(rem["kpa"], 2), "kPa")]
    if st is not None:
        cls = ("Insensitive" if st < 2 else "Medium sensitive" if st < 4 else "Sensitive" if st < 8
               else "Extra sensitive" if st < 16 else "Quick")
        values += [("Sensitivity St", round(st, 3), ""), ("Sensitivity class", cls, "")]
    if mu is not None:
        values += [("Bjerrum μ", round(mu, 3), ""), ("Corrected su peak", round(mu * peak["kpa"], 2), "kPa")]
        if rem:
            values.append(("Corrected su remoulded", round(mu * rem["kpa"], 2), "kPa"))
    rot = [num(r.get("rotation")) for r in rows]
    charts = [chart("Vane dial reading", axis("Rotation (°)"), axis("Dial reading (div)"),
                    series("Undisturbed", [(x, num(r.get("dial_uc"))) for x, r in zip(rot, rows) if x is not None]),
                    series("Remoulded", [(x, num(r.get("dial_rc"))) for x, r in zip(rot, rows) if x is not None]),
                    series("Shaft", [(x, num(r.get("dial_shaft"))) for x, r in zip(rot, rows) if x is not None], dash=True))]
    notes = [
        "Force = a × maximum dial reading + b; torque = (force − shaft friction force) × torque arm; su = K × torque.",
        "Conversion uses one foot = 30.48 cm (one psf = 0.04788 kPa).",
        "The shaft friction reading is converted with the same calibration as the vane readings.",
    ]
    if mu is not None:
        notes.append("Bjerrum correction μ = 1.7 − 0.54 log PI, limited to a maximum of one.")
    else:
        notes.append("Enter the plasticity index to apply the Bjerrum correction.")
    return result(
        summary=[("su peak", round(peak["kpa"], 2), "kPa"), ("su remoulded", round(rem["kpa"], 2) if rem else None, "kPa"),
                 ("St", round(st, 3) if st is not None else None, "")],
        values=values, charts=charts if any(x is not None for x in rot) else [], notes=notes,
        method="Field vane shear test (torque to undrained shear strength)")


# Hvorslev (1951) shape factors F (m) for a test section of length L (m) and diameter D (m).
CONDITIONS = [
    ("section", "Uncased section of length L in uniform soil"),
    ("section_boundary", "Uncased section of length L just below an impermeable layer"),
    ("casing_end", "Open end of a flush casing in uniform soil"),
    ("casing_end_boundary", "Open end of a flush casing at an impermeable layer"),
]


def shape_factor(condition: str, length: Optional[float], diameter: float) -> float:
    if condition in ("casing_end", "casing_end_boundary"):
        return (2.75 if condition == "casing_end" else 2.0) * diameter
    if not length or length <= 0:
        raise CalcError("Enter the length of the test section")
    ratio = length / diameter if condition == "section" else 2 * length / diameter
    return 2 * math.pi * length / math.asinh(ratio)


def _perm_geometry(data: Dict[str, Any]) -> Dict[str, Any]:
    top = num(data.get("test_top"))
    if top is None:
        raise CalcError("Depth to the top of the test section is required")
    cond = _txt(data.get("condition")) or "section"
    length = num(data.get("test_length")) if cond.startswith("section") else 0.0
    d_mm = num(data.get("hole_diameter"))
    if not d_mm or d_mm <= 0:
        raise CalcError("Diameter of the test section is required")
    d = d_mm / 1000
    f = shape_factor(cond, length, d)
    stick = num(data.get("stick_up")) or 0.0
    centre = top + (length or 0.0) / 2
    gwl = num(data.get("gwl"))
    below_gwl = gwl is not None and gwl <= centre
    ref = gwl if below_gwl else centre  # depth of the equilibrium (reference) level
    assert ref is not None
    casing = num(data.get("casing_diameter")) or d_mm
    return {"top": top, "length": length or 0.0, "d": d, "f": f, "stick": stick, "ref": ref, "below_gwl": below_gwl,
            "area": math.pi * (casing / 1000) ** 2 / 4, "cond": cond}


def _perm_values(g: Dict[str, Any]) -> List[Value]:
    return [("Shape factor F", round(g["f"], 4), "m"),
            ("Test condition", "Below the groundwater level" if g["below_gwl"] else "Above the groundwater level", "")]


PERM_NOTES = [
    "Shape factors after Hvorslev (1951): uncased section F = 2πL / asinh(L/D), or asinh(2L/D) below an impermeable layer; flush casing end F = 2.75 D, or 2 D at an impermeable layer.",
    "Below the groundwater level the head is measured to the groundwater level; above it, to the centre of the test section.",
]


def perm_constant(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.03 constant head test: k = Q / (F H)."""
    g = _perm_geometry(data)
    level = num(data.get("water_level"))
    level = g["stick"] if level is None else level
    head = num(data.get("head"))
    head = head if head is not None else level + g["ref"]
    if head <= 0:
        raise CalcError("The head must be greater than zero")
    rows: List[List[Any]] = []
    ks: List[float] = []
    elapsed = 0.0
    pts = []
    for r in _rows(data, "readings"):
        t, v = num(r.get("time_min")), num(r.get("volume_l"))
        if t is None or v is None:
            continue
        if t <= 0:
            raise CalcError("Time intervals must be greater than zero")
        q = v / 1000 / (t * 60)  # m³/s
        k = q / (g["f"] * head)
        elapsed += t
        ks.append(k)
        pts.append((elapsed, k * 100))
        rows.append([elapsed, t, v, rnd(q * 1000 * 60, 4), k, k * 100])
    if not ks:
        raise CalcError("Enter the readings with time and volume")
    k_all = sum(ks) / len(ks)
    k_last = sum(ks[-3:]) / len(ks[-3:])
    values = _perm_values(g) + [("Head H", round(head, 3), "m"), ("Readings", len(ks), ""),
                                ("k (mean of all readings)", rnd(k_all, 3), "m/s"), ("k (mean of all readings)", rnd(k_all * 100, 3), "cm/s"),
                                ("k (mean of the last three readings)", rnd(k_last, 3), "m/s")]
    return result(
        summary=[("k", rnd(k_all * 100, 3), "cm/s"), ("k", rnd(k_all, 3), "m/s")],
        values=values,
        tables=[table("Constant head readings", ["Elapsed time (min)", "Interval (min)", "Volume (L)", "Flow (L/min)", "k (m/s)", "k (cm/s)"], rows)],
        charts=[chart("Permeability per reading", axis("Elapsed time (min)"), axis("k (cm/s)", log=True), series("k", pts))],
        notes=PERM_NOTES + ["k = Q / (F H); the reported k is the mean of all readings, compare it with the last readings for steady flow."],
        method="Constant head borehole permeability test (Hvorslev)")


def _variable_head(data: Dict[str, Any], rising: bool) -> Dict[str, Any]:
    g = _perm_geometry(data)
    eq = g["stick"] + g["ref"]  # equilibrium level as depth below the top of the casing
    pts: List[Tuple[float, float]] = []
    for r in _rows(data, "readings"):
        t, d = num(r.get("time_min")), num(r.get("depth_to_water"))
        if t is None or d is None:
            continue
        h = d - eq if rising else eq - d
        if h > 0:
            pts.append((t * 60, h))
    pts.sort()
    if len(pts) < 2:
        raise CalcError("Enter at least two readings with the water level away from the equilibrium level")
    rows: List[List[Any]] = []
    for i in range(1, len(pts)):
        (t1, h1), (t2, h2) = pts[i - 1], pts[i]
        k = g["area"] / (g["f"] * (t2 - t1)) * math.log(h1 / h2) if t2 > t1 and h2 > 0 else None
        rows.append([t2 / 60, h2, k, k * 100 if k is not None else None])
    _, slope, r2 = linear_fit([t for t, _ in pts], [math.log(h) for _, h in pts])
    if slope >= 0:
        raise CalcError("The head does not decrease with time; check the readings")
    k_fit = -slope * g["area"] / g["f"]
    h0 = pts[0][1]
    values = _perm_values(g) + [("Standpipe area A", rnd(g["area"], 4), "m²"), ("Initial head h0", round(h0, 3), "m"),
                                ("Basic time lag T0", rnd(-1 / slope / 60, 4), "min"),
                                ("k", rnd(k_fit, 3), "m/s"), ("k", rnd(k_fit * 100, 3), "cm/s"), ("Fit r²", round(r2, 4), "")]
    title = "Rising head readings" if rising else "Falling head readings"
    return result(
        summary=[("k", rnd(k_fit * 100, 3), "cm/s"), ("k", rnd(k_fit, 3), "m/s")],
        values=values,
        tables=[table(title, ["Time (min)", "Head h (m)", "k for the interval (m/s)", "k for the interval (cm/s)"], rows)],
        charts=[chart("Head ratio against time", axis("Time (min)"), axis("h/h0", log=True),
                      series("h/h0", [(t / 60, h / h0) for t, h in pts]))],
        notes=PERM_NOTES + ["k = A ln(h1/h2) / (F (t2 − t1)); the reported k comes from the straight-line fit of ln h against time."],
        method=("Rising" if rising else "Falling") + " head borehole permeability test (Hvorslev)")


def perm_falling(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.03 falling head test."""
    return _variable_head(data, rising=False)


def perm_rising(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.03 rising head test (bail or pump down, then record the recovery)."""
    return _variable_head(data, rising=True)


PRESSURE_TO_BAR = {"bar": 1.0, "kgcm2": 0.980665, "mpa": 10.0, "kpa": 0.01}


def lugeon(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.03 packer (Lugeon) test: Lu = (Q/L)(10/P) per stage and Houlsby flow regime."""
    top, bottom = num(data.get("test_top")), num(data.get("test_bottom"))
    if top is None or bottom is None:
        raise CalcError("Enter the top and bottom of the test section")
    length = bottom - top
    if length <= 0:
        raise CalcError("The bottom of the test section must be below its top")
    unit = PRESSURE_TO_BAR.get(_txt(data.get("pressure_unit")) or "bar", 1.0)
    gauge_h = num(data.get("gauge_height")) or 0.0
    centre = (top + bottom) / 2
    gwl = num(data.get("gwl"))
    column = gauge_h + (min(gwl, centre) if gwl is not None else centre)
    p_water = 9.81 * column / 100  # bar
    stages: List[Dict[str, Any]] = []
    for i, r in enumerate(_rows(data, "stages")):
        p, v = num(r.get("pressure")), num(r.get("volume_l"))
        flow = num(r.get("flow_lpm"))
        t = num(r.get("duration_min")) or 10.0
        if p is None or (v is None and flow is None):
            continue
        q = flow if flow is not None else (v or 0.0) / t
        loss = (num(r.get("friction_loss")) or 0.0) * unit
        p_eff = p * unit + p_water - loss
        if p_eff <= 0:
            raise CalcError("The effective pressure must be greater than zero")
        lu = q / length * 10 / p_eff
        stages.append({"name": _txt(r.get("stage")) or str(i + 1), "pg": p, "q": q, "p": p_eff, "lu": lu})
    if len(stages) < 3:
        raise CalcError("Enter at least three pressure stages")
    lus = [s["lu"] for s in stages]
    rep, regime = _houlsby(lus)
    rows = [[s["name"], s["pg"], round(s["p"], 3), round(s["q"], 3), round(s["q"] / length, 4), round(s["lu"], 3)] for s in stages]
    return result(
        summary=[("Lugeon value", rnd(rep, 3), "Lu"), ("Flow behaviour", regime, "")],
        values=[("Test section length", round(length, 3), "m"), ("Water column to the section", round(column, 3), "m"),
                ("Water column pressure", round(p_water, 3), "bar"), ("Flow behaviour", regime, ""),
                ("Lugeon value", rnd(rep, 3), "Lu"), ("Approximate k", rnd(rep * 1.3e-7, 2), "m/s")],
        tables=[table("Pressure stages", ["Stage", "Gauge pressure", "Effective pressure (bar)", "Flow (L/min)",
                                          "Flow per metre (L/min/m)", "Lugeon (Lu)"], rows)],
        charts=[chart("Lugeon value per stage", axis("Stage"), axis("Lugeon (Lu)"),
                      series("Lu", [(i + 1, s["lu"]) for i, s in enumerate(stages)])),
                chart("Flow against pressure", axis("Effective pressure (bar)"), axis("Flow per metre (L/min/m)"),
                      series("Stages", [(s["p"], s["q"] / length) for s in stages]))],
        notes=["Lu = (Q / L) × (10 / P) with Q in L/min, L in m and P the effective pressure at the test section in bar.",
               "Effective pressure = gauge pressure + water column from the gauge to the groundwater level (or to the section centre when it is dry) − friction loss.",
               "The flow behaviour and the reported value follow Houlsby (1976): laminar the mean, turbulent the highest-pressure stage, dilation and void filling the lowest, wash-out the highest.",
               "The permeability shown uses one Lugeon ≈ 1.3 × 10⁻⁷ m/s and is approximate."],
        method="Water pressure (Lugeon) test, Houlsby (1976) interpretation")


def _houlsby(lus: List[float]) -> Tuple[float, str]:
    """Representative Lugeon value and flow regime (Houlsby 1976) from the stage values A-B-C-B-A."""
    mean = sum(lus) / len(lus)
    lo, hi = min(lus), max(lus)
    if hi <= 1e-12:
        return 0.0, "Laminar"
    if hi - lo <= 0.2 * mean:
        return mean, "Laminar"
    first, last = lus[0], lus[-1]
    mid = len(lus) // 2
    peak = lus[mid]
    rising = all(lus[i] <= lus[i + 1] * 1.05 for i in range(len(lus) - 1))
    falling = all(lus[i] >= lus[i + 1] * 0.95 for i in range(len(lus) - 1))
    if rising and last > first * 1.2:
        return last, "Wash-out"
    if falling and last < first / 1.2:
        return last, "Void filling"
    others = lus[:mid] + lus[mid + 1:]
    if peak > max(others) * 1.2:
        return min(others), "Dilation"
    if peak < min(others) / 1.2:
        return peak, "Turbulent"
    if last > first * 1.2:
        return last, "Wash-out"
    if last < first / 1.2:
        return last, "Void filling"
    return mean, "Not clear"


def test_pit(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.06 test pit: layer thicknesses and pocket penetrometer readings."""
    layers: List[List[Any]] = []
    for r in _rows(data, "layers"):
        top, bottom = num(r.get("top")), num(r.get("bottom"))
        if top is None or bottom is None:
            continue
        if bottom <= top:
            raise CalcError("A layer bottom must be below its top")
        layers.append([top, bottom, round(bottom - top, 3), _txt(r.get("uscs")).upper(), _txt(r.get("description")),
                       dict(WALL_OPTIONS).get(_txt(r.get("wall")), "")])
    layers.sort(key=lambda x: x[0])
    pp, pts, qus = _pp_table(_rows(data, "pocket"), "depth")
    if not layers and not pp:
        raise CalcError("Enter the layers or the pocket penetrometer readings")
    notes = []
    gaps = any(abs(layers[i][0] - layers[i - 1][1]) > 1e-6 for i in range(1, len(layers)))
    if gaps:
        notes.append("The layers are not continuous; check the depths.")
    total = num(data.get("total_depth"))
    if layers and total is not None and abs(layers[-1][1] - total) > 1e-6:
        notes.append("The deepest layer does not reach the total depth of the pit.")
    tables = []
    if layers:
        tables.append(table("Layers", ["From (m)", "To (m)", "Thickness (m)", "USCS", "Description", "Pit wall"], layers))
    if pp:
        tables.append(table("Pocket penetrometer", ["Depth (m)", "qu (kg/cm²)", "qu (kPa)", "su ≈ qu/2 (kPa)", "Consistency"], pp))
        notes.append("The pocket penetrometer gives an index of the unconfined strength; su ≈ qu/2 is an estimate only.")
    values: List[Value] = [("Layers", len(layers), "")]
    if layers:
        values.append(("Logged depth", layers[-1][1], "m"))
    if qus:
        values += [("Minimum qu", rnd(min(qus), 3), "kPa"), ("Maximum qu", rnd(max(qus), 3), "kPa")]
    return result(
        summary=[("Layers", len(layers), ""), ("Logged depth", layers[-1][1] if layers else None, "m")],
        values=values, tables=tables,
        charts=[chart("Pocket penetrometer qu", axis("qu (kPa)"), axis("Depth (m)", reverse=True), series("qu", pts))] if pts else [],
        notes=notes, method="Test pit log")


def cbr_field(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.07 in-place CBR: pressure from the proving ring, zero correction, CBR at 0.1 and 0.2 in."""
    ring = num(data.get("ring_factor"))
    if not ring:
        raise CalcError("Proving ring factor is required")
    area = num(data.get("piston_area")) or 3.0
    rule = _txt(data.get("report_rule")) or "astm"
    rows = sorted((r for r in _rows(data, "readings") if num(r.get("penetration")) is not None),
                  key=lambda r: float(r["penetration"]))
    if len(rows) < 3:
        raise CalcError("Enter the penetration readings")
    pen = [float(r["penetration"]) for r in rows]
    results: List[List[Any]] = []
    curves = []
    reported: List[float] = []
    notes = ["Pressure = dial reading × ring factor / piston area; CBR = corrected pressure / standard pressure (1000 psi at 0.1 in, 1500 psi at 0.2 in) × 100."]
    tbl: List[List[Any]] = [[p, round(p * 25.4, 2)] for p in pen]
    for name in ("a", "b", "c"):
        dials = [num(r.get("dial_" + name)) for r in rows]
        if all(d is None for d in dials):
            for line in tbl:
                line.append(None)
            continue
        pairs = [(p, d * ring / area) for p, d in zip(pen, dials) if d is not None]
        for line, d in zip(tbl, dials):
            line.append(round(d * ring / area, 2) if d is not None else None)
        xs, ps = [x for x, _ in pairs], [y for _, y in pairs]
        shift = num(data.get("zero_" + name)) or 0.0
        p1 = interpolate(0.1 + shift, xs, ps)
        p2 = interpolate(0.2 + shift, xs, ps)
        cbr1 = p1 / 1000 * 100 if p1 is not None else None
        cbr2 = p2 / 1500 * 100 if p2 is not None else None
        rep: Optional[float]
        if rule == "average" and cbr1 is not None and cbr2 is not None:
            rep = (cbr1 + cbr2) / 2
        elif cbr1 is not None and cbr2 is not None and cbr2 > cbr1:
            rep = cbr2
        else:
            rep = cbr1
        if rep is not None:
            reported.append(rep)
        label = "Test " + name.upper()
        results.append([label, shift, rnd(p1, 5), rnd(cbr1, 4), rnd(p2, 5), rnd(cbr2, 4), rnd(rep, 4)])
        curves.append(series(label, [(x - shift, y) for x, y in pairs]))
    if not results:
        raise CalcError("Enter the dial readings of at least one test")
    if rule == "average":
        notes.append("The reported CBR is the average of the values at 0.1 in and 0.2 in, as in the template; ASTM D4429 reports the value at 0.1 in.")
    else:
        notes.append("The reported CBR is the value at 0.1 in; when the value at 0.2 in is higher it is reported instead and the test should be repeated to confirm it.")
    notes.append("Enter a zero correction when the curve is concave upward at the start; the curve is then shifted by that penetration.")
    mean = _mean(reported)
    values: List[Value] = []
    for row in results:
        values += [(f"CBR {row[0]} at 0.1 in", row[3], "%"), (f"CBR {row[0]} at 0.2 in", row[5], "%"), (f"CBR {row[0]}", row[6], "%")]
    values.append(("CBR (mean of the tests)", rnd(mean, 4), "%"))
    return result(
        summary=[("CBR", rnd(mean, 4), "%")],
        values=values,
        tables=[table("CBR results", ["Test", "Zero correction (in)", "Pressure at 0.1 in (psi)", "CBR at 0.1 in (%)",
                                      "Pressure at 0.2 in (psi)", "CBR at 0.2 in (%)", "Reported CBR (%)"], results),
                table("Pressure readings", ["Penetration (in)", "Penetration (mm)", "Pressure A (psi)", "Pressure B (psi)", "Pressure C (psi)"], tbl)],
        charts=[chart("Pressure against penetration", axis("Corrected penetration (in)"), axis("Pressure (psi)"), *curves)],
        notes=notes, method="In-place CBR (ASTM D4429)")


POISSON = {"gravel": 0.27, "sand": 0.30, "silt": 0.35, "silty_clay": 0.38, "clay": 0.42}


def _bilinear_yield(pts: List[Tuple[float, float]]) -> Optional[float]:
    """Yield pressure from two straight lines fitted on log pressure against log settlement."""
    data = [(math.log10(p), math.log10(s)) for p, s in pts if p > 0 and s > 0]
    if len(data) < 4:
        return None
    best: Optional[Tuple[float, float]] = None
    for k in range(2, len(data) - 1):
        a, b = data[:k], data[k - 1:]
        try:
            a0, a1, _ = linear_fit([x for x, _ in a], [y for _, y in a])
            b0, b1, _ = linear_fit([x for x, _ in b], [y for _, y in b])
        except CalcError:
            continue
        sse = sum((y - a0 - a1 * x) ** 2 for x, y in a) + sum((y - b0 - b1 * x) ** 2 for x, y in b)
        if abs(a1 - b1) < 1e-9 or b1 <= a1:
            continue
        x = (a0 - b0) / (b1 - a1)
        if best is None or sse < best[0]:
            best = (sse, x)
    return 10 ** best[1] if best else None


def plt(data: Dict[str, Any]) -> Dict[str, Any]:
    """03.08 plate load test: pressure–settlement curve, yield, allowable pressure, k at 1.25 mm, E."""
    b_mm = num(data.get("plate_diameter"))
    if not b_mm or b_mm <= 0:
        raise CalcError("Plate diameter or width is required")
    ring = num(data.get("ring_factor"))
    if not ring:
        raise CalcError("Proving ring factor is required")
    square = data.get("plate_shape") == "square"
    b = b_mm / 1000
    area = b * b if square else math.pi * b * b / 4  # m²
    resolution = num(data.get("dial_resolution")) or 0.01
    zeros = [num(data.get(f"zero_{i}")) or 0.0 for i in (1, 2, 3)]
    steps: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for r in _rows(data, "readings"):
        step = num(r.get("step"))
        if step is None:
            continue
        s = int(step)
        if s not in steps:
            steps[s] = {"div": None, "dial": None}
            order.append(s)
        if num(r.get("ring_div")) is not None:
            steps[s]["div"] = num(r.get("ring_div"))
        dials = [(num(r.get(f"dial_{i}")), zeros[i - 1]) for i in (1, 2, 3)]
        used = [d - z for d, z in dials if d is not None]
        if used:
            steps[s]["dial"] = sum(used) / len(used)
    pts: List[Dict[str, Any]] = [{"step": 0, "kg": 0.0, "p": 0.0, "s": 0.0, "branch": "Loading"}]
    peak = 0.0
    for s in order:
        st = steps[s]
        if st["div"] is None or st["dial"] is None:
            continue
        kg = st["div"] * ring
        p = kg * 9.80665 / 1000 / area  # kPa
        branch = "Loading" if kg >= peak else "Unloading"
        peak = max(peak, kg)
        pts.append({"step": s, "kg": kg, "p": p, "s": st["dial"] * resolution, "branch": branch})
    if len(pts) < 3:
        raise CalcError("Enter the readings of at least two load steps")
    load = [p for p in pts if p["branch"] == "Loading"]
    unload = [p for p in pts if p["branch"] == "Unloading"]
    soil = _txt(data.get("soil")) or "clay"
    nu = num(data.get("poisson"))
    nu = POISSON.get(soil, 0.35) if nu is None else nu
    io = 0.886 if square else math.pi / 4
    fs = num(data.get("factor_of_safety")) or 2.0
    q_yield = num(data.get("yield_pressure"))
    source = "Entered"
    if q_yield is None:
        q_yield = _bilinear_yield([(p["p"], p["s"]) for p in load])
        source = "Two-line fit on the log–log curve"
    ps, ss = [p["p"] for p in load], [p["s"] for p in load]
    q_allow = q_yield / fs if q_yield is not None else None
    s_allow = interpolate(q_allow, ps, ss) if q_allow is not None else None
    p125 = interpolate(1.25, ss, ps)
    k125 = p125 / 1.25 if p125 is not None else None  # kPa/mm = MN/m³
    e_mod = io * (1 - nu ** 2) * q_allow * b_mm / s_allow / 1000 if q_allow and s_allow else None  # MPa
    kv = q_allow / s_allow if q_allow and s_allow else None
    notes = [
        "Pressure = ring reading × ring factor / plate area; settlement = mean of the dial readings at the end of each step minus the zero readings.",
        "The modulus of subgrade reaction k is the pressure at 1.25 mm settlement divided by 1.25 mm for the plate tested; pavement values refer to a 762 mm (30 in) plate and a smaller plate gives a higher k.",
        "For clay k scales with the plate width: k for a 762 mm plate ≈ k × B / 762.",
        "E = Io (1 − ν²) q B / s for a rigid plate (Io = π/4 circular, 0.886 square), taken at the allowable pressure.",
    ]
    if q_yield is None:
        notes.append("The yield pressure could not be found; enter it from the log–log plot.")
    values: List[Value] = [
        ("Plate area", round(area * 1e4, 2), "cm²"), ("Maximum pressure", rnd(max(ps), 4), "kPa"),
        ("Maximum settlement", rnd(max(p["s"] for p in pts), 4), "mm"), ("Poisson's ratio ν", nu, ""), ("Shape factor Io", round(io, 3), ""),
        ("Yield pressure", rnd(q_yield, 4), "kPa"), ("Yield pressure", rnd(q_yield / KGCM2, 4) if q_yield else None, "kg/cm²"),
        ("Yield pressure from", source if q_yield is not None else "", ""),
        ("Allowable pressure", rnd(q_allow, 4), "kPa"), ("Settlement at the allowable pressure", rnd(s_allow, 4), "mm"),
        ("Kv at the allowable pressure", rnd(kv, 4), "MN/m³"), ("k at 1.25 mm (plate tested)", rnd(k125, 4), "MN/m³"),
        ("k for a 762 mm plate (clay)", rnd(k125 * b_mm / 762, 4) if k125 is not None else None, "MN/m³"),
        ("Elastic modulus E", rnd(e_mod, 4), "MPa"),
    ]
    rows = [[p["step"], p["branch"], round(p["kg"], 2), round(p["p"], 3), round(p["p"] / KGCM2, 5), round(p["s"], 4)] for p in pts]
    charts = [
        chart("Pressure against settlement", axis("Pressure (kPa)"), axis("Settlement (mm)", reverse=True),
              series("Loading", [(p["p"], p["s"]) for p in load]),
              series("Unloading", [(p["p"], p["s"]) for p in [load[-1]] + unload] if unload else [])),
        chart("Log pressure against log settlement", axis("Pressure (kPa)", log=True), axis("Settlement (mm)", log=True),
              series("Loading", [(p["p"], p["s"]) for p in load if p["p"] > 0 and p["s"] > 0], "points"),
              series("Yield pressure", [(q_yield, min(s for s in ss if s > 0)), (q_yield, max(ss))] if q_yield and any(s > 0 for s in ss) else [], "line", dash=True)),
    ]
    return result(
        summary=[("Yield pressure", rnd(q_yield, 4), "kPa"), ("Allowable pressure", rnd(q_allow, 4), "kPa"),
                 ("k at 1.25 mm", rnd(k125, 4), "MN/m³"), ("E", rnd(e_mod, 4), "MPa")],
        values=values,
        tables=[table("Pressure and settlement", ["Step", "Branch", "Load (kg)", "Pressure (kPa)", "Pressure (kg/cm²)", "Settlement (mm)"], rows)],
        charts=charts, notes=notes, method="Plate load test (ASTM D1194 / D1196)")


# --------------------------------------------------------------------------- #
# 04 Geophysics
# --------------------------------------------------------------------------- #

def resistivity_1d(data: Dict[str, Any]) -> Dict[str, Any]:
    """04.01 vertical electrical sounding: K, apparent resistivity, repeat error, sounding curve."""
    array = _txt(data.get("array")) or "schlumberger"
    limit = num(data.get("repeat_limit")) or 10.0
    rows: List[List[Any]] = []
    curve = []
    flagged = 0
    short_mn = 0
    for r in _rows(data, "readings"):
        ab2, mn2, a = num(r.get("ab2")), num(r.get("mn2")), num(r.get("a"))
        if array == "wenner":
            a = a if a is not None else (2 * ab2 / 3 if ab2 is not None else None)
            if a is None or a <= 0:
                continue
            k = 2 * math.pi * a
            ab2, mn2 = 1.5 * a, 0.5 * a
        else:
            if ab2 is None or mn2 is None:
                continue
            if mn2 <= 0 or ab2 <= mn2:
                raise CalcError("AB/2 must be larger than MN/2 and MN/2 greater than zero")
            k = math.pi * (ab2 ** 2 - mn2 ** 2) / (2 * mn2)
            if ab2 < 5 * mn2:
                short_mn += 1
        rhos = []
        for vk, ik in (("v1", "i1"), ("v2", "i2")):
            v, i = num(r.get(vk)), num(r.get(ik))
            if v is not None and i:
                rhos.append(k * v / i)
        if not rhos:
            continue
        avg = sum(rhos) / len(rhos)
        err = abs(rhos[0] - rhos[1]) / avg * 100 if len(rhos) == 2 and avg else None
        if err is not None and err > limit:
            flagged += 1
        rows.append([ab2, mn2, a if array == "wenner" else None, round(k, 3), rnd(rhos[0], 4),
                     rnd(rhos[1], 4) if len(rhos) > 1 else None, rnd(avg, 4), rnd(err, 3),
                     "Repeat" if err is not None and err > limit else ""])
        if avg > 0:
            curve.append((ab2, avg))
    if not rows:
        raise CalcError("Enter the electrode spacings with voltage and current")
    notes = ["ρa = K × V / I with V in mV and I in mA; Wenner K = 2πa, Schlumberger K = π((AB/2)² − (MN/2)²) / MN.",
             "Readings whose two measurements differ by more than the repeat limit should be measured again."]
    if short_mn:
        notes.append("Some Schlumberger readings have AB smaller than five times MN.")
    rhos_all = [r[6] for r in rows]
    return result(
        summary=[("Readings", len(rows), ""), ("ρa minimum", rnd(min(rhos_all), 4), "Ω·m"), ("ρa maximum", rnd(max(rhos_all), 4), "Ω·m")],
        values=[("Readings", len(rows), ""), ("ρa minimum", rnd(min(rhos_all), 4), "Ω·m"), ("ρa maximum", rnd(max(rhos_all), 4), "Ω·m"),
                ("Readings to repeat", flagged, "")],
        tables=[table("Apparent resistivity", ["AB/2 (m)", "MN/2 (m)", "a (m)", "K (m)", "ρa 1 (Ω·m)", "ρa 2 (Ω·m)",
                                               "ρa mean (Ω·m)", "Repeat error (%)", "Check"], rows)],
        charts=[chart("Sounding curve", axis("AB/2 (m)", log=True), axis("Apparent resistivity (Ω·m)", log=True),
                      series("ρa", sorted(curve)))],
        notes=notes, method="DC resistivity sounding (ASTM D6431)")


# Median depth of investigation z/a (Edwards 1977, as tabulated by Loke) for n = 1..8.
_DEPTH = {
    "dipole_dipole": [0.416, 0.697, 0.962, 1.220, 1.476, 1.730, 1.983, 2.236],
    "wenner_schlumberger": [0.52, 0.93, 1.32, 1.71, 2.09, 2.48, 2.86, 3.25],
    "pole_dipole": [0.52, 0.93, 1.32, 1.71, 2.09, 2.48, 2.86, 3.25],
}


def _pseudo_depth(array: str, n: int, a: float) -> float:
    if array == "wenner":
        return 0.519 * n * a
    table_ = _DEPTH[array]
    if n <= len(table_):
        return table_[n - 1] * a
    step = table_[-1] - table_[-2]
    return (table_[-1] + step * (n - len(table_))) * a


def resistivity_2d(data: Dict[str, Any]) -> Dict[str, Any]:
    """04.02 resistivity imaging: K, apparent resistivity, datum position and pseudo-depth."""
    array = _txt(data.get("array")) or "wenner"
    a = num(data.get("spacing"))
    if not a or a <= 0:
        raise CalcError("Unit electrode spacing a is required")
    start = num(data.get("line_start")) or 0.0
    next_c1: Dict[int, float] = {}
    rows: List[List[Any]] = []
    pts = []
    for r in _rows(data, "readings"):
        n_raw, v, i = num(r.get("n")), num(r.get("v")), num(r.get("i"))
        if n_raw is None or v is None or not i:
            continue
        n = int(n_raw)
        if n < 1:
            raise CalcError("The level n must be one or more")
        c1 = num(r.get("x"))  # position of the first (left-most) electrode
        if c1 is None:
            c1 = next_c1.get(n, start)
        next_c1[n] = c1 + a
        pos: List[Optional[float]]
        if array == "wenner":
            s = n * a
            pos = [c1, c1 + s, c1 + 2 * s, c1 + 3 * s]  # C1 P1 P2 C2
            k = 2 * math.pi * s
        elif array == "dipole_dipole":
            pos = [c1 + a, c1 + (n + 1) * a, c1 + (n + 2) * a, c1]  # C2 at c1, C1, P1, P2
            k = math.pi * n * (n + 1) * (n + 2) * a
        elif array == "wenner_schlumberger":
            pos = [c1, c1 + n * a, c1 + (n + 1) * a, c1 + (2 * n + 1) * a]
            k = math.pi * n * (n + 1) * a
        elif array == "pole_dipole":
            pos = [c1, c1 + n * a, c1 + (n + 1) * a, None]  # remote C2
            k = 2 * math.pi * n * (n + 1) * a
        else:
            raise CalcError("Choose the electrode array")
        if array == "pole_dipole":
            x = c1 + (n + 0.5) * a / 2  # half-way between C1 and the potential dipole centre
        else:
            x = sum(p for p in pos if p is not None) / 4
        z = _pseudo_depth(array, n, a)
        rho = k * v / i
        rows.append([n, pos[0], pos[1], pos[2], pos[3], round(k, 3), v, i, rnd(rho, 4), round(x, 3), round(z, 3)])
        if rho > 0:
            pts.append([rnd(x, 5), rnd(z, 5), rnd(rho, 5)])
    if not rows:
        raise CalcError("Enter the readings with level n, voltage and current")
    rhos = sorted(r[8] for r in rows)
    median = rhos[len(rhos) // 2] if len(rhos) % 2 else (rhos[len(rhos) // 2 - 1] + rhos[len(rhos) // 2]) / 2
    pseudo = {"title": "Apparent resistivity pseudo-section", "kind": "value",
              "x": axis("Distance along the line (m)"), "y": axis("Pseudo-depth (m)", reverse=True),
              "points": pts, "value_label": "Apparent resistivity (Ω·m)", "log_value": True}
    return result(
        summary=[("Data points", len(rows), ""), ("ρa median", rnd(median, 4), "Ω·m")],
        values=[("Data points", len(rows), ""), ("Levels", len({r[0] for r in rows}), ""),
                ("ρa minimum", rnd(rhos[0], 4), "Ω·m"), ("ρa median", rnd(median, 4), "Ω·m"), ("ρa maximum", rnd(rhos[-1], 4), "Ω·m")],
        tables=[table("Apparent resistivity", ["n", "C1 (m)", "P1 (m)", "P2 (m)", "C2 (m)", "K (m)", "V (mV)", "I (mA)",
                                               "ρa (Ω·m)", "Datum x (m)", "Pseudo-depth (m)"], thin(rows, 400))],
        charts=[pseudo],
        notes=["Wenner K = 2πna, dipole–dipole K = πn(n+1)(n+2)a, Wenner–Schlumberger K = πn(n+1)a, pole–dipole K = 2πn(n+1)a.",
               "Pseudo-depth is the median depth of investigation (Edwards 1977) and is for plotting only; the resistivity model comes from inversion.",
               "When the first electrode position is left empty the readings of each level start at the line start and move by one spacing a."],
        method="DC resistivity imaging (ASTM D6431)")


def _moduli(vp: Optional[float], vs: Optional[float], gamma: float) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Gmax (MPa), Poisson's ratio and E (MPa) from Vp, Vs (m/s) and unit weight (kN/m³)."""
    rho = gamma / G  # Mg/m³
    gmax = rho * vs ** 2 / 1000 if vs else None
    nu = None
    if vp and vs and vp > vs:
        nu = (vp ** 2 - 2 * vs ** 2) / (2 * (vp ** 2 - vs ** 2))
    e = 2 * gmax * (1 + nu) if gmax is not None and nu is not None else None
    return gmax, nu, e


def _vs30_values(layers: List[Tuple[float, float, float]]) -> Tuple[List[Value], List[str]]:
    vs30, covered = average_over_30m(layers)
    if vs30 is None:
        return [], []
    site = classify(vs=vs30)
    notes = ["Vs30 = 30 / Σ(d / Vs) over the top 30 m; the deepest velocity is extended to 30 m when the data stop short."]
    return [("Vs30", rnd(vs30, 4), "m/s"), ("Site class (SNI 1726:2019)", f"{site} – {CLASS_NAMES[site]}", ""),
            ("Data to depth", rnd(covered, 4), "m")], notes


def downhole(data: Dict[str, Any]) -> Dict[str, Any]:
    """04.03 downhole seismic: slant distance, interval Vp and Vs, Gmax, ν, E, Vs30."""
    x = num(data.get("source_offset"))
    if x is None or x < 0:
        raise CalcError("Source offset is required")
    dz0 = num(data.get("source_elevation")) or 0.0  # source elevation above the top of the hole
    gamma_default = num(data.get("unit_weight"))
    assumed = gamma_default is None
    gamma_default = 18.0 if gamma_default is None else gamma_default
    rows = sorted((r for r in _rows(data, "readings") if num(r.get("depth")) is not None and
                   (num(r.get("tp")) is not None or num(r.get("ts")) is not None)), key=lambda r: float(r["depth"]))
    if len(rows) < 2:
        raise CalcError("Enter at least two depths with arrival times")
    prev: Dict[str, Tuple[float, float]] = {"tp": (0.0, 0.0), "ts": (0.0, 0.0)}  # (slant distance, time s)
    out: List[List[Any]] = []
    layers: List[Tuple[float, float, float]] = []
    vp_pts, vs_pts = [], []
    last_depth = 0.0
    bad = 0
    near = 0
    for r in rows:
        depth = float(r["depth"])
        slant = math.sqrt((dz0 + depth) ** 2 + x ** 2)
        vel: Dict[str, Optional[float]] = {}
        direct: Dict[str, Optional[float]] = {}
        for key in ("tp", "ts"):
            t_ms = num(r.get(key))
            vel[key] = direct[key] = None
            if t_ms is None or t_ms <= 0:
                continue
            t = t_ms / 1000
            direct[key] = slant / t
            l0, t0 = prev[key]
            if t > t0 and slant > l0:
                vel[key] = (slant - l0) / (t - t0)
            else:
                bad += 1
            prev[key] = (slant, t)
        gamma = num(r.get("unit_weight")) or gamma_default
        gmax, nu, e = _moduli(vel["tp"], vel["ts"], gamma)
        flag = ""
        if depth < 3 * x:
            flag = "Close to the source"
            near += 1
        out.append([round(last_depth, 3), depth, round(slant, 3), num(r.get("tp")), num(r.get("ts")),
                    rnd(direct["tp"], 4), rnd(direct["ts"], 4), rnd(vel["tp"], 4), rnd(vel["ts"], 4), gamma,
                    rnd(gmax, 4), rnd(nu, 3), rnd(e, 4), flag])
        if vel["ts"]:
            layers.append((last_depth, depth, vel["ts"]))
            vs_pts += [(vel["ts"], last_depth), (vel["ts"], depth)]
        if vel["tp"]:
            vp_pts += [(vel["tp"], last_depth), (vel["tp"], depth)]
        last_depth = depth
    values: List[Value] = [("Depths", len(out), "")]
    vs30_vals, vs30_notes = _vs30_values(layers)
    values += vs30_vals
    notes = ["Slant distance = √((source elevation + depth)² + offset²); interval velocity = Δ slant distance / Δ arrival time between successive depths.",
             "Gmax = ρ Vs², ν = (Vp² − 2Vs²) / (2(Vp² − Vs²)), E = 2 Gmax (1 + ν) with ρ = γ / g.",
             "Straight ray paths are assumed (no refraction correction)."] + vs30_notes
    if near:
        notes.append("Results at depths within three source offsets are questionable (ASTM D7400).")
    if bad:
        notes.append("Some arrival times do not increase with depth; those intervals have no velocity.")
    if assumed:
        notes.append("A unit weight of eighteen kN/m³ is assumed where none is entered.")
    vs30 = vs30_vals[0][1] if vs30_vals else None
    return result(
        summary=[("Vs30", vs30, "m/s"), ("Site class", vs30_vals[1][1].split(" ")[0] if vs30_vals else None, "")],
        values=values,
        tables=[table("Downhole velocities", ["From (m)", "To (m)", "Slant distance (m)", "tP (ms)", "tS (ms)",
                                              "Vp apparent (m/s)", "Vs apparent (m/s)", "Vp interval (m/s)", "Vs interval (m/s)",
                                              "γ (kN/m³)", "Gmax (MPa)", "ν", "E (MPa)", "Check"], out)],
        charts=[chart("Interval velocity", axis("Velocity (m/s)"), axis("Depth (m)", reverse=True),
                      series("Vp", vp_pts, "line"), series("Vs", vs_pts, "line"))],
        notes=notes, method="Downhole seismic test, interval method (ASTM D7400)")


def crosshole(data: Dict[str, Any]) -> Dict[str, Any]:
    """04.04 crosshole seismic: direct and interval velocities, Gmax, ν, E, Vs30."""
    l1_default, l2_default = num(data.get("spacing_r1")), num(data.get("spacing_r2"))
    gamma_default = num(data.get("unit_weight"))
    assumed = gamma_default is None
    gamma_default = 18.0 if gamma_default is None else gamma_default
    rows = sorted((r for r in _rows(data, "readings") if num(r.get("depth")) is not None), key=lambda r: float(r["depth"]))
    out: List[List[Any]] = []
    vp_pts, vs_pts = [], []
    prof = []
    for r in rows:
        depth = float(r["depth"])
        l1 = num(r.get("l1")) or l1_default
        l2 = num(r.get("l2")) or l2_default

        def v(dist: Optional[float], key: str) -> Optional[float]:
            t = num(r.get(key))
            return dist / (t / 1000) if dist and t and t > 0 else None

        vp1, vs1 = v(l1, "tp1"), v(l1, "ts1")
        vp2, vs2 = v(l2, "tp2"), v(l2, "ts2")

        def interval(k1: str, k2: str) -> Optional[float]:
            t1, t2 = num(r.get(k1)), num(r.get(k2))
            if l1 and l2 and t1 is not None and t2 is not None and t2 > t1 and l2 > l1:
                return (l2 - l1) / ((t2 - t1) / 1000)
            return None

        vpi, vsi = interval("tp1", "tp2"), interval("ts1", "ts2")
        vp = vpi or vp1
        vs = vsi or vs1
        if vp is None and vs is None:
            continue
        gamma = num(r.get("unit_weight")) or gamma_default
        gmax, nu, e = _moduli(vp, vs, gamma)
        out.append([depth, l1, rnd(vp1, 4), rnd(vs1, 4), l2, rnd(vp2, 4), rnd(vs2, 4), rnd(vpi, 4), rnd(vsi, 4),
                    gamma, rnd(gmax, 4), rnd(nu, 3), rnd(e, 4)])
        if vp:
            vp_pts.append((vp, depth))
        if vs:
            vs_pts.append((vs, depth))
            prof.append((depth, vs))
    if not out:
        raise CalcError("Enter the depths with source–receiver distances and arrival times")
    layers = []
    for i, (d, vs_) in enumerate(prof):
        top = 0.0 if i == 0 else (prof[i - 1][0] + d) / 2
        base = d if i + 1 == len(prof) else (d + prof[i + 1][0]) / 2
        if base > top:
            layers.append((top, base, vs_))
    vs30_vals, vs30_notes = _vs30_values(layers)
    notes = ["Direct velocity = source–receiver distance / travel time; interval velocity = (l2 − l1) / (t2 − t1) between the two receivers and is used when available.",
             "Gmax = ρ Vs², ν = (Vp² − 2Vs²) / (2(Vp² − Vs²)), E = 2 Gmax (1 + ν) with ρ = γ / g.",
             "Use distances corrected with the borehole deviation survey."] + vs30_notes
    if assumed:
        notes.append("A unit weight of eighteen kN/m³ is assumed where none is entered.")
    return result(
        summary=[("Depths", len(out), ""), ("Vs30", vs30_vals[0][1] if vs30_vals else None, "m/s")],
        values=[("Depths", len(out), "")] + vs30_vals,
        tables=[table("Crosshole velocities", ["Depth (m)", "l1 (m)", "Vp direct R1 (m/s)", "Vs direct R1 (m/s)", "l2 (m)",
                                               "Vp direct R2 (m/s)", "Vs direct R2 (m/s)", "Vp interval (m/s)", "Vs interval (m/s)",
                                               "γ (kN/m³)", "Gmax (MPa)", "ν", "E (MPa)"], out)],
        charts=[chart("Crosshole velocity", axis("Velocity (m/s)"), axis("Depth (m)", reverse=True),
                      series("Vp", vp_pts), series("Vs", vs_pts))],
        notes=notes, method="Crosshole seismic test (ASTM D4428/D4428M)")


def thermal_resistivity(data: Dict[str, Any]) -> Dict[str, Any]:
    """04.05 thermal needle probe: λ = Q / (4π S) from the slope of T against ln t; R = 1/λ."""
    q = num(data.get("heat_input"))
    if q is None:
        i, e, length = num(data.get("current")), num(data.get("voltage")), num(data.get("probe_length"))
        if not i or not e or not length:
            raise CalcError("Enter the heater current, voltage and probe length, or the heat input")
        q = e * i / (length / 1000)
    if q <= 0:
        raise CalcError("The heat input must be greater than zero")
    readings = [(num(r.get("time")), num(r.get("temperature")), _txt(r.get("phase")) or "heating")
                for r in _rows(data, "readings")]
    heat = sorted((t, tt) for t, tt, ph in readings if t is not None and tt is not None and ph == "heating" and t > 0)
    cool = sorted((t, tt) for t, tt, ph in readings if t is not None and tt is not None and ph == "cooling")
    if len(heat) < 3:
        raise CalcError("Enter at least three heating readings")
    t1 = num(data.get("heating_time")) or heat[-1][0]
    lo = num(data.get("fit_start"))
    hi = num(data.get("fit_end"))
    lo = t1 / 3 if lo is None else lo
    hi = t1 if hi is None else hi
    fit_h = [(math.log(t), tt) for t, tt in heat if lo <= t <= hi]
    if len(fit_h) < 3:
        raise CalcError("At least three heating readings must lie in the fitting window")
    _, s_h, r2_h = linear_fit([x for x, _ in fit_h], [y for _, y in fit_h])
    if s_h <= 0:
        raise CalcError("The temperature does not rise during heating; check the readings")
    lam_h = q / (4 * math.pi * s_h)
    lams = [lam_h]
    values: List[Value] = [("Heat input Q", round(q, 3), "W/m"), ("Heating slope S", round(s_h, 4), "K"),
                           ("λ heating", round(lam_h, 3), "W/(m·K)"), ("Heating fit r²", round(r2_h, 4), "")]
    cool_fit = [(math.log(t / (t - t1)), tt) for t, tt in cool if t - t1 >= t1 / 3]
    if len(cool_fit) >= 3:
        _, s_c, r2_c = linear_fit([x for x, _ in cool_fit], [y for _, y in cool_fit])
        if s_c > 0:
            lam_c = q / (4 * math.pi * s_c)
            lams.append(lam_c)
            values += [("Cooling slope S", round(s_c, 4), "K"), ("λ cooling", round(lam_c, 3), "W/(m·K)"),
                       ("Cooling fit r²", round(r2_c, 4), "")]
    lam = sum(lams) / len(lams)
    rt = 1 / lam
    values += [("Thermal conductivity λ", round(lam, 3), "W/(m·K)"), ("Thermal resistivity R", round(rt, 4), "m·K/W"),
               ("Thermal resistivity R", round(rt * 100, 2), "°C·cm/W")]
    charts = [chart("Temperature against time", axis("Time (s)", log=True), axis("Temperature (°C)"),
                    series("Heating", heat), series("Cooling", cool))]
    notes = ["λ = Q / (4π S) with Q = E I / L and S the slope of temperature against ln t (heating) or ln(t / (t − t1)) (cooling); R = 1 / λ.",
             "Unless a window is entered, the first third of the heating time is left out of the fit; λ is the mean of heating and cooling when both are available."]
    return result(
        summary=[("λ", round(lam, 3), "W/(m·K)"), ("R", round(rt * 100, 2), "°C·cm/W")],
        values=values, charts=charts, notes=notes, method="Thermal needle probe (ASTM D5334)")


# Options shared with sheets_field.py (kept here so the result tables can show their labels).
TEST_OPTIONS = [
    ("borehole", "Borehole / SPT"), ("cpt", "CPT / sondir"), ("cptu", "CPTu"), ("test_pit", "Test pit"),
    ("permeability", "Permeability test"), ("vane", "Vane shear test"), ("plt", "Plate load test"), ("cbr", "Field CBR"),
    ("resistivity", "Resistivity"), ("seismic", "Downhole / crosshole seismic"), ("survey", "Survey"), ("other", "Other"),
]
UNIT_OPTIONS = [("point", "point"), ("test", "test"), ("m", "m"), ("line", "line"), ("unit", "unit"), ("set", "set")]
WALL_OPTIONS = [("north", "North wall"), ("east", "East wall"), ("south", "South wall"), ("west", "West wall"), ("all", "All walls")]
