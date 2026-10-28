"""Export borehole logs as an AGS4 file (AGS Data Format, edition 4.1.1).

AGS4 is the data-exchange format for ground investigation data used by consultants,
contractors and tools such as gINT, HoleBASE and OpenGround. Only standard groups and
headings are used, so the file validates against the AGS 4.1.1 standard dictionary.

What this app records maps to AGS4 like this:

* PROJ  - one project per file
* LOCA  - one row per borehole (ID, type, ground level, final depth, dates, lat/lon)
* HDPH  - the hole from 0 m to the final depth, with method, rig (HDPH_EXC), wireline core
          barrel size (HDPH_BTYP), contractor and logger
* HDIA  - borehole diameter, CDIA - casing diameter (when recorded)
* WSTG  - the groundwater depth (when groundwater was encountered)

* GEOL  - strata (top, base, description; GEOL_LEG from the USCS group where it maps)
* ISPT  - SPT tests (seating and test blows, N, reported result, refusal penetration, and the
          blows and penetration of the seating drive and the two 150 mm test increments)
* SAMP  - samples (top, base, standard AGS4 sample type, reference)
* CORE  - core runs (TCR, SCR, RQD, core diameter of the wireline size)

The depth groups come from the borehole's depth data (details.py). The daily log's own
summary (one soil description, USCS class and average SPT N60) stays in LOCA_REM.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import OrderedDict
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import local_today, producer_name
from .models import CORE_SIZES

AGS_EDITION = "4.1.1"

# Drilling methods offered by the app -> standard AGS4 abbreviations (ABBR list).
# LOCA_TYPE and HDPH_TYPE have slightly different standard lists.
_KNOWN_METHODS: Dict[str, Tuple[str, str, str]] = {
    # method: (LOCA_TYPE code, HDPH_TYPE code, description)
    "wash boring + spt": ("W", "W", "Wash boring"),
    "rotary wash + spt": ("RO", "RO", "Rotary open hole"),
    "hollow stem auger": ("AUGH", "AUGH", "Hollow Stem Auger"),
    "coring + spt": ("RC", "RC", "Rotary cored"),
    "cpt / cptu (sondir)": ("SCP", "SCP", "Static cone penetrometer"),
    "hand auger": ("HA", "HA", "Hand Auger"),
}
# USCS group -> AGS4 standard legend code (GEOL_LEG); dual symbols use the first group.
_USCS_LEGEND: Dict[str, Tuple[str, str]] = {
    "CL": ("201", "CLAY"), "CH": ("201", "CLAY"), "OH": ("229", "Organic CLAY"),
    "ML": ("301", "SILT"), "MH": ("301", "SILT"), "OL": ("305", "Organic SILT"),
    "SW": ("401", "SAND"), "SP": ("401", "SAND"), "SC": ("402", "Clayey SAND"), "SM": ("403", "Silty SAND"),
    "GW": ("501", "GRAVEL"), "GP": ("501", "GRAVEL"), "GC": ("502", "Clayey GRAVEL"), "GM": ("503", "Silty GRAVEL"),
    "PT": ("601", "PEAT"),
}
_SAMPLE_DESCRIPTIONS = {
    "U": "Undisturbed sample - open drive",
    "UT": "Thin wall open drive tube sampler",
    "TW": "Thin walled push in sample",
    "P": "Piston sample",
    "D": "Small disturbed sample",
    "B": "Bulk disturbed sample",
    "SPTLS": "Standard penetration test liner sample",
    "C": "Core sample",
    "W": "Water sample",
}


def _legend(uscs: str) -> Optional[Tuple[str, str]]:
    first = re.split(r"[-/ ]", (uscs or "").strip().upper())[0]
    return _USCS_LEGEND.get(first)


_STANDARD_CODES = {
    ("LOCA_TYPE", code) for code in ("W", "RO", "AUGH", "RC", "SCP", "HA")
} | {("HDPH_TYPE", code) for code in ("W", "RO", "RC", "SCP", "HA")}

_UNIT_DESCRIPTIONS = {
    "%": "percent",
    "m": "metre",
    "mm": "millimetre",
    "yyyy-mm-dd": "year month day",
}
_TYPE_DESCRIPTIONS = {
    "0DP": "Value; required number of decimal places, 0",
    "2DP": "Value; required number of decimal places, 2",
    "DMS": "Degrees: Minutes: Seconds",
    "DT": "Date time in international format",
    "ID": "Unique Identifier",
    "PA": "Text listed in ABBR Group",
    "PU": "Text listed in UNIT Group",
    "X": "Text",
}

Group = Tuple[str, List[Tuple[str, str, str]], List[Dict[str, str]]]  # name, [(heading, unit, type)], rows


class AGSExportError(ValueError):
    """The selection cannot be exported (e.g. no logs for the project)."""


def _ascii(value: Any) -> str:
    """AGS4 files must be ASCII: transliterate accents (é -> e), drop the rest."""
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip()


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dp(value: Any, places: int) -> str:
    number = _number(value)
    return "" if number is None else f"{number:.{places}f}"


def _date(value: Any) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _dms(value: Any, limit: float) -> str:
    """Decimal degrees -> AGS4 DMS text, e.g. -6.17512 -> "-06:10:30.43"."""
    number = _number(value)
    if number is None or abs(number) > limit:
        return ""
    sign = "-" if number < 0 else ""
    total_seconds = round(abs(number) * 3600, 2)
    degrees, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    width = 3 if limit > 90 else 2
    return f"{sign}{int(degrees):0{width}d}:{int(minutes):02d}:{seconds:05.2f}"


def _project_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", _ascii(name)).strip("-").upper()
    return (slug or "PROJECT")[:40]


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _render(groups: Sequence[Group]) -> str:
    lines: List[str] = []
    for name, headings, rows in groups:
        if lines:
            lines.append("")
        lines.append(",".join(_quote(v) for v in ("GROUP", name)))
        lines.append(",".join(_quote(v) for v in ["HEADING"] + [h for h, _, _ in headings]))
        lines.append(",".join(_quote(v) for v in ["UNIT"] + [u for _, u, _ in headings]))
        lines.append(",".join(_quote(v) for v in ["TYPE"] + [t for _, _, t in headings]))
        for row in rows:
            lines.append(",".join(_quote(v) for v in ["DATA"] + [row.get(h, "") for h, _, _ in headings]))
    # AGS4 rule 2a: every line ends with CR LF.
    return "\r\n".join(lines) + "\r\n"


def _method_codes(methods: Iterable[str]) -> Dict[str, Tuple[str, str, str]]:
    """Code per distinct method; unknown methods get M1, M2, ... described in ABBR."""
    codes: Dict[str, Tuple[str, str, str]] = OrderedDict()
    custom = 0
    for method in methods:
        key = method.strip().lower()
        if not key or key in codes:
            continue
        if key in _KNOWN_METHODS:
            codes[key] = _KNOWN_METHODS[key]
        else:
            custom += 1
            code = f"M{custom}"
            codes[key] = (code, code, _ascii(method))
    return codes


def _summary_remark(row: Dict[str, Any]) -> str:
    parts = []
    if row.get("USCS_Class"):
        parts.append(f"USCS: {_ascii(row['USCS_Class'])}")
    if _number(row.get("Avg_SPT_N60")) is not None:
        parts.append(f"Average SPT N60: {_number(row['Avg_SPT_N60']):g}")
    core = str(row.get("CoreSize") or "").upper()
    if core in CORE_SIZES:
        parts.append(f"Core size: {core} wireline (core {CORE_SIZES[core][1]:g} mm)")
    if _number(row.get("TargetDepth_m")) is not None:
        parts.append(f"Target depth: {_number(row['TargetDepth_m']):g} m")
    if row.get("SoilDescription"):
        parts.append(f"Soil: {_ascii(row['SoilDescription'])}")
    if row.get("Remarks"):
        parts.append(f"Remarks: {_ascii(row['Remarks'])}")
    return ". ".join(p.rstrip(".") for p in parts)


def build_ags(
    project: str,
    reports: List[Dict[str, Any]],
    *,
    today: Optional[date] = None,
    depth_data: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """Return (filename, AGS4 text) for every log of ``project``.

    ``depth_data`` maps BoreholeID -> {"layers", "spt", "samples", "core"} (details.py).
    """
    wanted = project.strip().lower()
    rows = [r for r in reports if str(r.get("ProjectName") or "").strip().lower() == wanted]
    if not rows:
        raise AGSExportError(f"No borehole logs found for project '{project}'")
    rows.sort(key=lambda r: str(r.get("BoreholeID") or ""))

    project_name = str(rows[0].get("ProjectName") or project).strip()
    proj_id = _project_id(project_name)
    methods = _method_codes(str(r.get("DrillingMethod") or "") for r in rows)

    def codes_for(row: Dict[str, Any]) -> Tuple[str, str]:
        found = methods.get(str(row.get("DrillingMethod") or "").strip().lower())
        return (found[0], found[1]) if found else ("", "")

    sites = sorted({_ascii(r.get("SiteName")) for r in rows if r.get("SiteName")})
    contractors = sorted({_ascii(r.get("Contractor")) for r in rows if r.get("Contractor")})

    proj: Group = (
        "PROJ",
        [("PROJ_ID", "", "ID"), ("PROJ_NAME", "", "X"), ("PROJ_LOC", "", "X"), ("PROJ_CONT", "", "X"), ("PROJ_MEMO", "", "X")],
        [{
            "PROJ_ID": proj_id,
            "PROJ_NAME": _ascii(project_name),
            "PROJ_LOC": "; ".join(sites),
            "PROJ_CONT": "; ".join(contractors),
            "PROJ_MEMO": f"Exported from {producer_name()} daily borehole logs",
        }],
    )
    tran: Group = (
        "TRAN",
        [("TRAN_ISNO", "", "X"), ("TRAN_DATE", "yyyy-mm-dd", "DT"), ("TRAN_PROD", "", "X"), ("TRAN_STAT", "", "X"),
         ("TRAN_DESC", "", "X"), ("TRAN_AGS", "", "X"), ("TRAN_RECV", "", "X"), ("TRAN_DLIM", "", "X"),
         ("TRAN_RCON", "", "X")],
        [{
            "TRAN_ISNO": "1",
            "TRAN_DATE": (today or local_today()).strftime("%Y-%m-%d"),
            "TRAN_PROD": producer_name(),
            "TRAN_STAT": "Preliminary",
            "TRAN_DESC": "Borehole summary from daily logs",
            "TRAN_AGS": AGS_EDITION,
            "TRAN_RECV": "Not specified",
            "TRAN_DLIM": "|",
            "TRAN_RCON": "+",
        }],
    )

    # IDs must stay unique after the ASCII conversion (e.g. "BH-é1" and "BH-e1").
    seen: Dict[str, str] = {}
    for row in rows:
        original = str(row.get("BoreholeID") or "")
        converted = _ascii(original)
        if not converted:
            raise AGSExportError(f"BoreholeID '{original}' has no ASCII characters; rename it before exporting")
        if converted.lower() in seen:
            raise AGSExportError(
                f"BoreholeIDs '{seen[converted.lower()]}' and '{original}' become the same AGS4 ID "
                f"'{converted}'; rename one before exporting"
            )
        seen[converted.lower()] = original

    loca_rows, hdph_rows, hdia_rows, cdia_rows, wstg_rows = [], [], [], [], []
    geol_rows: List[Dict[str, str]] = []
    ispt_rows: List[Dict[str, str]] = []
    samp_rows: List[Dict[str, str]] = []
    core_rows: List[Dict[str, str]] = []
    for row in rows:
        loca_id = _ascii(row.get("BoreholeID"))
        depth = (depth_data or {}).get(str(row.get("BoreholeID") or ""), {})
        for layer in depth.get("layers", []):
            uscs = _ascii(layer.get("uscs"))
            legend = _legend(uscs)
            geol_rows.append({
                "LOCA_ID": loca_id,
                "GEOL_TOP": _dp(layer.get("top"), 2),
                "GEOL_BASE": _dp(layer.get("base"), 2),
                "GEOL_DESC": _ascii(layer.get("description")) or (legend[1] if legend else ""),
                "GEOL_LEG": legend[0] if legend else "",
                "GEOL_REM": f"USCS: {uscs}" if uscs else "",
            })
        for test in depth.get("spt", []):
            seat, inc1 = int(test.get("seat") or 0), int(test.get("inc1") or 0)
            inc2 = test.get("inc2")
            n_value = inc1 + int(inc2 or 0)
            pen = test.get("penetration_mm")
            test_pen = int(pen) if pen else 300
            reported = f"{n_value}/{test_pen}mm" if test_pen < 300 else f"N={n_value}"
            # The two 150 mm test increments with their penetration (INC3/PEN3, INC4/PEN4), so the
            # blows per increment survive an export and a later import.
            first_pen = test_pen if inc2 is None else 150
            increments = {"ISPT_INC1": str(seat), "ISPT_PEN1": "150", "ISPT_INC3": str(inc1), "ISPT_PEN3": str(first_pen)}
            if inc2 is not None:
                increments.update({"ISPT_INC4": str(int(inc2)), "ISPT_PEN4": str(max(test_pen - 150, 0))})
            ispt_rows.append({
                **increments,
                "LOCA_ID": loca_id,
                "ISPT_TOP": _dp(test.get("depth"), 2),
                "ISPT_SEAT": str(seat),
                "ISPT_MAIN": str(n_value),
                "ISPT_NPEN": str(150 + test_pen),
                "ISPT_NVAL": str(n_value),
                "ISPT_REP": reported,
                "ISPT_TYPE": "S",
                "ISPT_REM": _ascii(test.get("remarks")),
            })
        type_counts: Dict[str, int] = {}
        # Generated references (D1, D2 ...) skip any reference the user typed.
        used_refs = {_ascii(s.get("ref")).upper() for s in depth.get("samples", []) if _ascii(s.get("ref"))}
        for sample in depth.get("samples", []):
            code = str(sample.get("type") or "").upper()
            if code not in _SAMPLE_DESCRIPTIONS:
                continue
            ref = _ascii(sample.get("ref"))
            while not ref:
                type_counts[code] = type_counts.get(code, 0) + 1
                candidate = f"{code}{type_counts[code]}"
                if candidate.upper() not in used_refs:
                    ref = candidate
                    used_refs.add(candidate.upper())
            top = _dp(sample.get("top"), 2)
            samp_rows.append({
                "LOCA_ID": loca_id,
                "SAMP_TOP": top,
                "SAMP_REF": ref,
                "SAMP_TYPE": code,
                "SAMP_ID": f"{loca_id}-{ref}-{top}",
                "SAMP_BASE": _dp(sample.get("base"), 2),
                "SAMP_REM": _ascii(sample.get("remarks")),
            })
        core_size = str(row.get("CoreSize") or "").upper()
        for run in depth.get("core", []):
            core_rows.append({
                "LOCA_ID": loca_id,
                "CORE_TOP": _dp(run.get("top"), 2),
                "CORE_BASE": _dp(run.get("base"), 2),
                "CORE_PREC": _dp(run.get("tcr"), 0),
                "CORE_SREC": _dp(run.get("scr"), 0),
                "CORE_RQD": _dp(run.get("rqd"), 0),
                "CORE_DIAM": _dp(CORE_SIZES[core_size][1], 0) if core_size in CORE_SIZES else "",
                "CORE_REM": _ascii(run.get("remarks")),
            })
        loca_type, hdph_type = codes_for(row)
        core = str(row.get("CoreSize") or "").upper()
        final_depth = _dp(row.get("FinalDepth_m"), 2)
        loca_rows.append({
            "LOCA_ID": loca_id,
            "LOCA_TYPE": loca_type,
            "LOCA_GL": _dp(row.get("GroundElevation_mRL"), 2),
            "LOCA_REM": _summary_remark(row),
            "LOCA_FDEP": final_depth,
            "LOCA_STAR": _date(row.get("StartDate")),
            "LOCA_ENDD": _date(row.get("EndDate")),
            "LOCA_LOCA": _ascii(row.get("SiteName")),
            "LOCA_LAT": _dms(row.get("Latitude"), 90),
            "LOCA_LON": _dms(row.get("Longitude"), 180),
            "LOCA_LLZ": "WGS84" if _number(row.get("Latitude")) is not None else "",
        })
        if final_depth and hdph_type:
            hdph_rows.append({
                "LOCA_ID": loca_id,
                "HDPH_TOP": "0.00",
                "HDPH_BASE": final_depth,
                "HDPH_TYPE": hdph_type,
                "HDPH_EXC": _ascii(row.get("DrillRig")),
                "HDPH_BTYP": f"{core} wireline" if core in CORE_SIZES else "",
                "HDPH_LOG": _ascii(row.get("LoggingGeologist")),
                "HDPH_METH": _ascii(row.get("DrillingMethod")),
                "HDPH_CONT": _ascii(row.get("Contractor")),
            })
        diameter = _number(row.get("BoreholeDiameter_mm"))
        diameter_note = ""
        if not (diameter and diameter > 0) and core in CORE_SIZES:
            diameter = CORE_SIZES[core][0]
            diameter_note = f"Nominal {core} wireline hole size"
        if final_depth and diameter and diameter > 0:
            hdia_rows.append({
                "LOCA_ID": loca_id, "HDIA_DPTH": final_depth, "HDIA_DIAM": _dp(diameter, 0), "HDIA_REM": diameter_note,
            })
        casing = _number(row.get("CasingInstalled_mm"))
        if final_depth and casing and casing > 0:
            cdia_rows.append({
                "LOCA_ID": loca_id,
                "CDIA_DPTH": final_depth,
                "CDIA_DIAM": _dp(casing, 0),
                "CDIA_REM": "Casing depth not recorded in the daily log; final hole depth shown",
            })
        groundwater = str(row.get("GroundwaterEncountered")).strip().lower() in {"true", "yes", "1"}
        gw_depth = _dp(row.get("GroundwaterDepth_m"), 2)
        if groundwater and gw_depth:
            wstg_rows.append({"LOCA_ID": loca_id, "WSTG_DPTH": gw_depth, "WSTG_REM": "Groundwater depth from daily log"})

    loca: Group = (
        "LOCA",
        [("LOCA_ID", "", "ID"), ("LOCA_TYPE", "", "PA"), ("LOCA_GL", "m", "2DP"), ("LOCA_REM", "", "X"),
         ("LOCA_FDEP", "m", "2DP"), ("LOCA_STAR", "yyyy-mm-dd", "DT"), ("LOCA_ENDD", "yyyy-mm-dd", "DT"),
         ("LOCA_LAT", "", "DMS"), ("LOCA_LON", "", "DMS"), ("LOCA_LLZ", "", "X"), ("LOCA_LOCA", "", "X")],
        loca_rows,
    )
    data_groups: List[Group] = [loca]
    if hdph_rows:
        data_groups.append((
            "HDPH",
            [("LOCA_ID", "", "ID"), ("HDPH_TOP", "m", "2DP"), ("HDPH_BASE", "m", "2DP"), ("HDPH_TYPE", "", "PA"),
             ("HDPH_EXC", "", "X"), ("HDPH_BTYP", "", "X"), ("HDPH_LOG", "", "X"), ("HDPH_METH", "", "X"),
             ("HDPH_CONT", "", "X")],
            hdph_rows,
        ))
    if hdia_rows:
        data_groups.append((
            "HDIA",
            [("LOCA_ID", "", "ID"), ("HDIA_DPTH", "m", "2DP"), ("HDIA_DIAM", "mm", "0DP"), ("HDIA_REM", "", "X")],
            hdia_rows,
        ))
    if cdia_rows:
        data_groups.append((
            "CDIA",
            [("LOCA_ID", "", "ID"), ("CDIA_DPTH", "m", "2DP"), ("CDIA_DIAM", "mm", "0DP"), ("CDIA_REM", "", "X")],
            cdia_rows,
        ))
    if core_rows:
        data_groups.append((
            "CORE",
            [("LOCA_ID", "", "ID"), ("CORE_TOP", "m", "2DP"), ("CORE_BASE", "m", "2DP"), ("CORE_PREC", "%", "0DP"),
             ("CORE_SREC", "%", "0DP"), ("CORE_RQD", "%", "0DP"), ("CORE_DIAM", "mm", "0DP"), ("CORE_REM", "", "X")],
            core_rows,
        ))
    if geol_rows:
        data_groups.append((
            "GEOL",
            [("LOCA_ID", "", "ID"), ("GEOL_TOP", "m", "2DP"), ("GEOL_BASE", "m", "2DP"), ("GEOL_DESC", "", "X"),
             ("GEOL_LEG", "", "PA"), ("GEOL_REM", "", "X")],
            geol_rows,
        ))
    if ispt_rows:
        data_groups.append((
            "ISPT",
            [("LOCA_ID", "", "ID"), ("ISPT_TOP", "m", "2DP"), ("ISPT_SEAT", "", "0DP"), ("ISPT_MAIN", "", "0DP"),
             ("ISPT_NPEN", "mm", "0DP"), ("ISPT_NVAL", "", "0DP"), ("ISPT_REP", "", "X"), ("ISPT_TYPE", "", "PA"),
             ("ISPT_INC1", "", "0DP"), ("ISPT_INC3", "", "0DP"), ("ISPT_INC4", "", "0DP"), ("ISPT_PEN1", "mm", "0DP"),
             ("ISPT_PEN3", "mm", "0DP"), ("ISPT_PEN4", "mm", "0DP"), ("ISPT_REM", "", "X")],
            ispt_rows,
        ))
    if samp_rows:
        data_groups.append((
            "SAMP",
            [("LOCA_ID", "", "ID"), ("SAMP_TOP", "m", "2DP"), ("SAMP_REF", "", "X"), ("SAMP_TYPE", "", "PA"),
             ("SAMP_ID", "", "ID"), ("SAMP_BASE", "m", "2DP"), ("SAMP_REM", "", "X")],
            samp_rows,
        ))
    if wstg_rows:
        data_groups.append(("WSTG", [("LOCA_ID", "", "ID"), ("WSTG_DPTH", "m", "2DP"), ("WSTG_REM", "", "X")], wstg_rows))

    # ABBR, TYPE and UNIT must list exactly what the file uses. Headings follow the order of
    # the standard dictionary (AGS4 rule 7).
    abbr_rows = []
    used_codes: set[Tuple[str, str]] = set()
    for group_rows, heading in (
        (loca_rows, "LOCA_TYPE"), (hdph_rows, "HDPH_TYPE"), (geol_rows, "GEOL_LEG"),
        (ispt_rows, "ISPT_TYPE"), (samp_rows, "SAMP_TYPE"),
    ):
        used_codes.update((heading, r[heading]) for r in group_rows if r.get(heading))
    descriptions: Dict[Tuple[str, str], str] = {("ISPT_TYPE", "S"): "Split spoon"}
    descriptions.update({("SAMP_TYPE", code): desc for code, desc in _SAMPLE_DESCRIPTIONS.items()})
    descriptions.update({("GEOL_LEG", code): desc for code, desc in _USCS_LEGEND.values()})
    standard = set(_STANDARD_CODES) | {key for key in descriptions if key[0] != "LOCA_TYPE" and key[0] != "HDPH_TYPE"}
    for loca_code, hdph_code, desc in methods.values():
        descriptions[("LOCA_TYPE", loca_code)] = desc
        descriptions[("HDPH_TYPE", hdph_code)] = desc
    for heading, code in sorted(used_codes):
        abbr_rows.append({
            "ABBR_HDNG": heading,
            "ABBR_CODE": code,
            "ABBR_DESC": descriptions.get((heading, code), code),
            "ABBR_LIST": "AGS4" if (heading, code) in standard else producer_name(),
        })
    abbr: Group = (
        "ABBR",
        [("ABBR_HDNG", "", "X"), ("ABBR_CODE", "", "X"), ("ABBR_DESC", "", "X"), ("ABBR_LIST", "", "X")],
        abbr_rows,
    )

    content_groups = [proj, tran] + data_groups + ([abbr] if abbr_rows else [])
    used_types = {t for _, headings, _ in content_groups for _, _, t in headings} | {"X", "PU"}
    used_units = {u for _, headings, _ in content_groups for _, u, _ in headings if u}
    type_group: Group = (
        "TYPE",
        [("TYPE_TYPE", "", "X"), ("TYPE_DESC", "", "X")],
        [{"TYPE_TYPE": t, "TYPE_DESC": _TYPE_DESCRIPTIONS[t]} for t in sorted(used_types)],
    )
    unit_group: Group = (
        "UNIT",
        [("UNIT_UNIT", "", "X"), ("UNIT_DESC", "", "X")],
        [{"UNIT_UNIT": u, "UNIT_DESC": _UNIT_DESCRIPTIONS[u]} for u in sorted(used_units)],
    )
    groups = content_groups + [type_group, unit_group]
    return f"{proj_id}.ags", _render(groups)
