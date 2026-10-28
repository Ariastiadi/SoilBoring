"""Import an AGS4 file into borehole logs, depth data and laboratory results.

The counterpart of ags.py (export). The file is read in three steps:

1. ``parse``: the AGS4 structure (GROUP / HEADING / UNIT / TYPE / DATA lines, AGS4 rules 1-5),
   with a light reader for AGS3 files ("**GROUP", "*HEADING", <UNITS>, <CONT>).
2. ``build_plan``: checks the key fields (rule 10a), the parent rows (rule 10c) and the units,
   converts what it can, and maps every borehole (LOCA) to a log, its depth data (GEOL, ISPT,
   SAMP, CORE, WSTG/WSTD) and the laboratory groups (LNMC, LLPL, GRAG, LDEN, LPDN, CMPG, SHBG,
   PTST, RPLT, RELD, GCHM) to lab test results. Nothing is stored; this is the preview.
3. ``apply``: stores the plan with the same functions the app uses (storage.save_report /
   update_report, details.save_details, records.save), skipping or overwriting boreholes that
   already exist.

Messages are {"text": English template, "params": {...}} so the interface can translate them.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from . import audit, details, docstore, records, storage
from .config import local_today
from .entities import ENTITIES, LAB_RESULTS
from .models import CORE_SIZES, Report

MAX_CHARS = 4_000_000
MAX_DATA_ROWS = 60_000
MAX_MESSAGES = 150

Msg = Dict[str, Any]


def msg(text: str, **params: Any) -> Msg:
    return {"text": text, "params": {k: str(v) for k, v in params.items()}}


class AGSImportError(ValueError):
    """The file cannot be read at all."""


# --------------------------------------------------------------------------- #
# 1. Parsing
# --------------------------------------------------------------------------- #

@dataclass
class Group:
    name: str
    line: int
    headings: List[str] = field(default_factory=list)
    units: Dict[str, str] = field(default_factory=dict)
    types: Dict[str, str] = field(default_factory=dict)
    rows: List[Dict[str, str]] = field(default_factory=list)
    has_unit: bool = False
    has_type: bool = False


@dataclass
class Parsed:
    fmt: str
    groups: "OrderedDict[str, Group]"
    errors: List[Msg]
    warnings: List[Msg]


_QUOTED_LINE = re.compile(r'^"(?:[^"]|"")*"(?:,"(?:[^"]|"")*")*$')
_GROUP_NAME = re.compile(r"^[A-Z0-9]{4}$")


class _Log:
    """Error and warning lists with a cap, so a broken file cannot flood the preview."""

    def __init__(self) -> None:
        self.errors: List[Msg] = []
        self.warnings: List[Msg] = []
        self.dropped = 0

    def error(self, text: str, **params: Any) -> None:
        if len(self.errors) < MAX_MESSAGES:
            self.errors.append(msg(text, **params))
        else:
            self.dropped += 1

    def warn(self, text: str, **params: Any) -> None:
        if len(self.warnings) < MAX_MESSAGES:
            self.warnings.append(msg(text, **params))
        else:
            self.dropped += 1


def _split(line: str) -> List[str]:
    return next(csv.reader([line], skipinitialspace=False))


def parse(text: str) -> Parsed:
    if len(text) > MAX_CHARS:
        raise AGSImportError("The file is too large (at most 4 MB)")
    text = text.lstrip("﻿")
    if not text.strip():
        raise AGSImportError("The file is empty")
    log = _Log()
    if not text.isascii():
        log.warn("The file has non-ASCII characters (AGS4 rule 1); they are kept as read.")
    if "\n" in text and "\r\n" not in text:
        log.warn("Lines end without CR LF (AGS4 rule 2a); the file is read anyway.")
    lines = text.splitlines()
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    if first.startswith('"**'):
        return _parse_ags3(lines, log)
    if not first.startswith('"GROUP"'):
        raise AGSImportError("This is not an AGS4 file: the first line must be a GROUP line")
    groups: "OrderedDict[str, Group]" = OrderedDict()
    current: Optional[Group] = None
    skipping = False
    unquoted = 0
    count = 0
    for no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if not _QUOTED_LINE.match(line):
            unquoted += 1
        try:
            fields = _split(line)
        except csv.Error:
            log.error("Line {line} cannot be read; it is skipped.", line=no)
            continue
        kind = fields[0].strip() if fields else ""
        if kind == "GROUP":
            name = fields[1].strip() if len(fields) > 1 else ""
            if not _GROUP_NAME.match(name):
                log.warn("Line {line}: group name '{group}' is not 4 capital letters or digits (AGS4 rule 19).", line=no, group=name)
            if name in groups:
                log.error("Group {group} appears more than once (AGS4 rule 3); the second one is skipped.", group=name)
                skipping, current = True, None
                continue
            skipping = False
            current = Group(name=name, line=no)
            groups[name] = current
            continue
        if skipping:
            continue
        if current is None:
            log.error("Line {line} is outside a group; it is skipped.", line=no)
            continue
        values = fields[1:]
        if kind == "HEADING":
            if current.headings:
                log.error("Group {group} has two HEADING rows (AGS4 rule 3).", group=current.name)
                continue
            seen: set = set()
            for h in values:
                if h in seen:
                    log.error("Group {group}: heading {heading} appears twice (AGS4 rule 9).", group=current.name, heading=h)
                seen.add(h)
            current.headings = [h.strip() for h in values]
        elif kind in ("UNIT", "TYPE"):
            if not current.headings:
                log.error("Group {group}: {row} row before the HEADING row (AGS4 rule 3).", group=current.name, row=kind)
                continue
            if len(values) != len(current.headings):
                log.error("Line {line} ({group}): the {row} row has {n} fields and the HEADING row {m} (AGS4 rule 4).",
                          line=no, group=current.name, row=kind, n=len(values), m=len(current.headings))
                values = (values + [""] * len(current.headings))[:len(current.headings)]
            target = current.units if kind == "UNIT" else current.types
            target.update({h: v.strip() for h, v in zip(current.headings, values)})
            if kind == "UNIT":
                current.has_unit = True
            else:
                current.has_type = True
        elif kind == "DATA":
            if not current.headings:
                log.error("Group {group}: DATA row before the HEADING row (AGS4 rule 3); it is skipped.", group=current.name)
                continue
            if len(values) != len(current.headings):
                log.error("Line {line} ({group}): the DATA row has {n} fields and the HEADING row {m} (AGS4 rule 4); "
                          "the row is skipped.", line=no, group=current.name, n=len(values), m=len(current.headings))
                continue
            count += 1
            if count > MAX_DATA_ROWS:
                raise AGSImportError("The file has too many data rows (at most 60 000)")
            row = {h: v for h, v in zip(current.headings, values)}
            row["_line"] = str(no)
            current.rows.append(row)
        else:
            log.error("Line {line} starts with '{word}' instead of GROUP, HEADING, UNIT, TYPE or DATA (AGS4 rule 3); "
                      "it is skipped.", line=no, word=kind[:20])
    if unquoted:
        log.warn("{n} lines have fields without double quotes (AGS4 rule 5); they are read anyway.", n=unquoted)
    for g in groups.values():
        if g.headings and (not g.has_unit or not g.has_type):
            log.warn("Group {group} has no UNIT or TYPE row (AGS4 rule 2b).", group=g.name)
    for name in ("PROJ", "TRAN", "UNIT", "TYPE"):
        if name not in groups:
            log.warn("Required group {group} is missing (AGS4 rules 13–17).", group=name)
    return Parsed("AGS4", groups, log.errors, log.warnings)


_AGS3_GROUPS = {"HOLE": "LOCA", "WSTK": "WSTG"}
_AGS3_HEADINGS = {"HOLE_ID": "LOCA_ID", "WSTK_DEP": "WSTG_DPTH", "WSTK_POST": "WSTD_POST", "WSTK_NMIN": "WSTD_NMIN"}


def _parse_ags3(lines: List[str], log: _Log) -> Parsed:
    """AGS3: "**GROUP", then "*HEADING" fields, "<UNITS>" and data rows; "<CONT>" continues a row."""
    groups: "OrderedDict[str, Group]" = OrderedDict()
    current: Optional[Group] = None
    count = 0
    for no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            fields = _split(line)
        except csv.Error:
            log.error("Line {line} cannot be read; it is skipped.", line=no)
            continue
        if not fields:
            continue
        head = fields[0].strip()
        if head.startswith("**"):
            name3 = head[2:].strip().lstrip("?")
            name = _AGS3_GROUPS.get(name3, name3)
            current = Group(name=name, line=no, has_type=True)
            if name in groups:
                log.error("Group {group} appears more than once (AGS4 rule 3); the second one is skipped.", group=name)
                current = None
            else:
                groups[name] = current
            continue
        if current is None:
            continue
        if head.startswith("*") and not current.headings:
            names = [f.strip().lstrip("*").lstrip("?") for f in fields]
            current.headings = [_AGS3_HEADINGS.get(h, ("LOCA_" + h[5:]) if h.startswith("HOLE_") else h) for h in names]
            continue
        if head == "<UNITS>":
            current.units.update({h: v.strip() for h, v in zip(current.headings, fields[1:])})
            current.has_unit = True
            continue
        if head == "<CONT>":
            if current.rows:
                last = current.rows[-1]
                for h, v in zip(current.headings[1:], fields[1:]):
                    if v:
                        last[h] = (last.get(h, "") + v)
            continue
        if not current.headings:
            continue
        if len(fields) != len(current.headings):
            log.error("Line {line} ({group}): the DATA row has {n} fields and the HEADING row {m} (AGS4 rule 4); "
                      "the row is skipped.", line=no, group=current.name, n=len(fields), m=len(current.headings))
            continue
        count += 1
        if count > MAX_DATA_ROWS:
            raise AGSImportError("The file has too many data rows (at most 60 000)")
        row = {h: v for h, v in zip(current.headings, fields)}
        row["_line"] = str(no)
        current.rows.append(row)
    log.warn("AGS3 file: read with the AGS3 group names converted (HOLE → LOCA, WSTK → WSTG); check the result.")
    return Parsed("AGS3", groups, log.errors, log.warnings)


# --------------------------------------------------------------------------- #
# Values and units
# --------------------------------------------------------------------------- #

def _num(value: Any) -> Optional[float]:
    text = str(value or "").strip().lstrip("#<>~").strip()
    if not text:
        return None
    try:
        out = float(text.replace(",", "."))
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _ascii(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip()


def _date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt, size in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10), ("%Y/%m/%d", 10)):
        try:
            return datetime.strptime(text[:size], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _dms(value: Any) -> Optional[float]:
    """AGS4 DMS text ("-06:10:30.43") or decimal degrees -> decimal degrees."""
    text = str(value or "").strip()
    if not text:
        return None
    if ":" not in text:
        return _num(text)
    sign = -1 if text.startswith("-") else 1
    parts = text.lstrip("+-").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    deg = nums[0] + (nums[1] if len(nums) > 1 else 0) / 60 + (nums[2] if len(nums) > 2 else 0) / 3600
    return sign * deg


def _unit_key(unit: str) -> str:
    return unit.strip().lower().replace(" ", "").replace("³", "3").replace("²", "2").replace("^", "")


_CONVERSIONS: Dict[str, Dict[str, float]] = {
    "m": {"m": 1, "mm": 0.001, "cm": 0.01, "ft": 0.3048},
    "mm": {"mm": 1, "m": 1000, "cm": 10, "in": 25.4},
    "%": {"%": 1},
    "Mg/m3": {"mg/m3": 1, "g/cm3": 1, "g/cc": 1, "t/m3": 1, "g/ml": 1, "kg/m3": 0.001},
    "m/s": {"m/s": 1, "cm/s": 0.01, "mm/s": 0.001},
    "MPa": {"mpa": 1, "mn/m2": 1, "n/mm2": 1, "kpa": 0.001, "kn/m2": 0.001},
    "kPa": {"kpa": 1, "kn/m2": 1, "mpa": 1000, "kg/cm2": 98.0665},
    "deg": {"deg": 1, "degrees": 1, "°": 1},
    "mg/l": {"mg/l": 1, "ppm": 1, "g/l": 1000, "ug/l": 0.001, "mg/kg": 1},
}

# Units the import expects (AGS4 standard dictionary) for the headings it reads.
EXPECTED_UNITS: Dict[str, str] = {
    **{h: "m" for h in ("LOCA_GL", "LOCA_FDEP", "HDPH_TOP", "HDPH_BASE", "HDIA_DPTH", "CDIA_DPTH", "GEOL_TOP", "GEOL_BASE",
                        "ISPT_TOP", "SAMP_TOP", "SAMP_BASE", "CORE_TOP", "CORE_BASE", "WSTG_DPTH", "WSTD_POST")},
    **{h: "mm" for h in ("HDIA_DIAM", "CDIA_DIAM", "ISPT_NPEN", "ISPT_PEN1", "ISPT_PEN2", "ISPT_PEN3", "ISPT_PEN4",
                         "ISPT_PEN5", "ISPT_PEN6")},
    **{h: "%" for h in ("CORE_PREC", "CORE_SREC", "CORE_RQD", "LNMC_MC", "LLPL_LL", "LLPL_PL", "GRAG_GRAV", "GRAG_SAND",
                        "GRAG_SILT", "GRAG_CLAY", "GRAG_FINE", "LDEN_MC", "CMPG_MCOP")},
    **{h: "Mg/m3" for h in ("LDEN_BDEN", "LDEN_DDEN", "LPDN_PDEN", "CMPG_MAXD", "RELD_DMAX", "RELD_DMIN")},
    "PTST_K": "m/s", "RPLT_PLSI": "MPa", "RPLT_PLS": "MPa", "SHBG_PCOH": "kPa", "SHBG_PHI": "deg",
}


class _Reader:
    """Reads values of one group with the unit conversion worked out once per heading."""

    def __init__(self, group: Group, log: _Log) -> None:
        self.group = group
        self.factor: Dict[str, float] = {}
        for h in group.headings:
            expected = EXPECTED_UNITS.get(h)
            if expected is None:
                continue
            unit = group.units.get(h, "")
            if not unit or _unit_key(unit) == _unit_key(expected):
                self.factor[h] = 1.0
                continue
            table = _CONVERSIONS.get(expected, {})
            factor = table.get(_unit_key(unit))
            if factor is None:
                log.warn("Group {group}: unit '{unit}' of {heading} is not understood; values are taken as {expected}.",
                         group=group.name, unit=unit, heading=h, expected=expected)
                factor = 1.0
            elif factor != 1:
                log.warn("Group {group}: {heading} converted from {unit} to {expected}.", group=group.name, heading=h,
                         unit=unit, expected=expected)
            self.factor[h] = factor

    def num(self, row: Dict[str, str], heading: str) -> Optional[float]:
        value = _num(row.get(heading))
        if value is None:
            return None
        return value * self.factor.get(heading, 1.0)


# --------------------------------------------------------------------------- #
# 2. Plan
# --------------------------------------------------------------------------- #

GROUP_USE: Dict[str, str] = {
    "PROJ": "Project", "TRAN": "Transfer details", "UNIT": "Units", "TYPE": "Data types", "ABBR": "Abbreviations",
    "DICT": "User-defined headings", "LOCA": "Boreholes", "HDPH": "Hole depths and method", "HDIA": "Hole diameter",
    "CDIA": "Casing diameter", "GEOL": "Strata", "ISPT": "SPT", "SAMP": "Samples", "CORE": "Core runs",
    "WSTG": "Groundwater", "WSTD": "Groundwater", "LNMC": "Water content", "LLPL": "Atterberg limits",
    "GRAG": "Grain size", "LDEN": "Density", "LPDN": "Specific gravity", "CMPG": "Compaction", "SHBG": "Direct shear",
    "PTST": "Permeability", "RPLT": "Point load", "RELD": "Relative density", "GCHM": "Chemistry",
    "CLSS": "Classification (AGS3)",
}
LAB_GROUPS = ("LNMC", "LLPL", "GRAG", "LDEN", "LPDN", "CMPG", "SHBG", "PTST", "RPLT", "RELD", "GCHM", "CLSS")
_SAMPLE_KEYS = ["LOCA_ID", "SAMP_TOP", "SAMP_REF", "SAMP_TYPE", "SAMP_ID", "SPEC_REF", "SPEC_DPTH"]
KEYS: Dict[str, List[str]] = {
    "PROJ": ["PROJ_ID"], "LOCA": ["LOCA_ID"], "HDPH": ["LOCA_ID", "HDPH_TOP", "HDPH_BASE", "HDPH_TYPE"],
    "HDIA": ["LOCA_ID", "HDIA_DPTH", "HDIA_DIAM"], "CDIA": ["LOCA_ID", "CDIA_DPTH", "CDIA_DIAM"],
    "GEOL": ["LOCA_ID", "GEOL_TOP", "GEOL_BASE"], "ISPT": ["LOCA_ID", "ISPT_TOP"],
    "SAMP": ["LOCA_ID", "SAMP_TOP", "SAMP_REF", "SAMP_TYPE", "SAMP_ID"], "CORE": ["LOCA_ID", "CORE_TOP", "CORE_BASE"],
    "WSTG": ["LOCA_ID", "WSTG_DPTH"], "WSTD": ["LOCA_ID", "WSTG_DPTH", "WSTD_NMIN"],
    **{g: _SAMPLE_KEYS for g in ("LNMC", "LLPL", "GRAG", "LDEN", "LPDN", "RPLT", "RELD", "SHBG")},
    "CMPG": _SAMPLE_KEYS + ["CMPG_TESN"], "PTST": _SAMPLE_KEYS + ["PTST_TESN"],
    "GCHM": _SAMPLE_KEYS + ["GCHM_CODE", "GCHM_METH", "GCHM_TTYP"],
}
METHOD_BY_CODE = {"W": "Wash Boring + SPT", "RO": "Rotary Wash + SPT", "AUGH": "Hollow Stem Auger", "RC": "Coring + SPT",
                  "SCP": "CPT / CPTu (Sondir)", "HA": "Hand Auger"}
SAMPLE_TYPE_ALIASES = {"LB": "B", "SPT": "SPTLS", "SPTL": "SPTLS", "CBR": "B", "ES": "D", "EW": "W", "WS": "W", "UT100": "UT"}
_USCS = r"(?:CL|CH|ML|MH|OL|OH|SW|SP|SM|SC|GW|GP|GM|GC|PT)(?:[-/](?:CL|CH|ML|MH|OL|OH|SW|SP|SM|SC|GW|GP|GM|GC))?"
_REM_PARTS = ("USCS", "Average SPT N60", "Core size", "Target depth", "Soil", "Remarks")


def _check_keys(parsed: Parsed, log: _Log) -> None:
    """AGS4 rule 10a: key fields present and unique; rule 10c: depth rows belong to a LOCA row."""
    loca_ids = {r.get("LOCA_ID", "").strip() for r in parsed.groups["LOCA"].rows} if "LOCA" in parsed.groups else set()
    for g in parsed.groups.values():
        keys = KEYS.get(g.name)
        if not keys or not g.headings:
            continue
        if "LOCA_ID" in keys and "LOCA_ID" not in g.headings:
            log.error("Group {group} has no {heading} heading (key field, AGS4 rule 10a); the group is skipped.",
                      group=g.name, heading="LOCA_ID")
            g.rows = []
            continue
        present = [k for k in keys if k in g.headings]
        seen: Dict[Tuple[str, ...], str] = {}
        kept: List[Dict[str, str]] = []
        orphans = 0
        for row in g.rows:
            key = tuple(row.get(k, "").strip() for k in present)
            if "LOCA_ID" in present and not row.get("LOCA_ID", "").strip():
                log.error("Line {line} ({group}): LOCA_ID is empty (AGS4 rule 10b); the row is skipped.",
                          line=row["_line"], group=g.name)
                continue
            if key in seen:
                log.error("Line {line} ({group}): same key fields as line {other} (AGS4 rule 10a); the row is skipped.",
                          line=row["_line"], group=g.name, other=seen[key])
                continue
            if g.name != "LOCA" and "LOCA_ID" in present and row.get("LOCA_ID", "").strip() not in loca_ids:
                orphans += 1
                continue
            seen[key] = row["_line"]
            kept.append(row)
        if orphans:
            log.warn("Group {group}: {n} rows refer to a LOCA_ID that is not in LOCA (AGS4 rule 10c); they are skipped.",
                     group=g.name, n=orphans)
        g.rows = kept


def _by_loca(group: Optional[Group]) -> Dict[str, List[Dict[str, str]]]:
    out: Dict[str, List[Dict[str, str]]] = {}
    for row in group.rows if group else []:
        out.setdefault(row.get("LOCA_ID", "").strip(), []).append(row)
    return out


def _abbr(parsed: Parsed) -> Dict[Tuple[str, str], str]:
    g = parsed.groups.get("ABBR")
    return {(r.get("ABBR_HDNG", ""), r.get("ABBR_CODE", "")): r.get("ABBR_DESC", "") for r in (g.rows if g else [])}


def _parse_loca_rem(text: str) -> Dict[str, str]:
    """LOCA_REM written by ags.py ("USCS: CH. Average SPT N60: 27.5. ... Remarks: ...") back into fields."""
    pattern = re.compile(r"(?:^|\. )(" + "|".join(re.escape(p) for p in _REM_PARTS) + r"): ")
    hits = list(pattern.finditer(text))
    if not hits or hits[0].start() != 0:
        return {"Remarks": text} if text else {}
    out: Dict[str, str] = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out[m.group(1)] = text[m.end():end].strip()
    fields: Dict[str, str] = {}
    if out.get("USCS"):
        fields["USCS_Class"] = out["USCS"]
    if _num(out.get("Average SPT N60")) is not None:
        fields["Avg_SPT_N60"] = _fmt(_num(out["Average SPT N60"]))
    size = (out.get("Core size") or "").split(" ")[0].upper()
    if size in CORE_SIZES:
        fields["CoreSize"] = size
    target = (out.get("Target depth") or "").removesuffix(" m")
    if _num(target) is not None:
        fields["TargetDepth_m"] = _fmt(_num(target))
    if out.get("Soil"):
        fields["SoilDescription"] = out["Soil"]
    if out.get("Remarks"):
        fields["Remarks"] = out["Remarks"]
    return fields


def _fmt(value: Optional[float], places: int = 6) -> str:
    if value is None:
        return ""
    text = f"{round(value, places):.{places}f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _first_error(exc: ValidationError) -> str:
    errs = exc.errors()
    if not errs:
        return "invalid value"
    text = str(errs[0].get("msg") or "invalid value").removeprefix("Value error, ")
    loc = [str(x) for x in errs[0].get("loc", ()) if not isinstance(x, int)]
    return f"{loc[-1]}: {text}" if loc and loc[-1] not in text else text


def _spt(row: Dict[str, str], rd: _Reader) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """One ISPT row -> app SPT (seat, two 150 mm increments, test penetration); (None, reason) when unusable."""
    depth = rd.num(row, "ISPT_TOP")
    if depth is None:
        return None, "no depth"
    incs = [(rd.num(row, f"ISPT_INC{i}"), rd.num(row, f"ISPT_PEN{i}")) for i in range(1, 7)]
    seat = _num(row.get("ISPT_SEAT"))
    if seat is None and (incs[0][0] is not None or incs[1][0] is not None):
        seat = (incs[0][0] or 0) + (incs[1][0] or 0)
    test = [(b, p) for b, p in incs[2:] if b is not None]
    inc1: Optional[float] = None
    inc2: Optional[float] = None
    pen: Optional[float] = None
    if test:
        # Blows in the first 150 mm of the test drive go to increment 1, the rest to increment 2.
        done = 0.0
        inc1 = 0.0
        for blows, p in test:
            p = 75.0 if p is None else p
            if done < 150 - 1e-6:
                inc1 += blows
            else:
                inc2 = (inc2 or 0.0) + blows
            done += p
        pen = done if done < 300 - 1e-6 else None
    else:
        n_value = _num(row.get("ISPT_NVAL"))
        if n_value is None:
            n_value = _num(row.get("ISPT_MAIN"))
        rep = str(row.get("ISPT_REP") or "")
        m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*mm", rep)
        if n_value is None and m:
            n_value = float(m.group(1))
        if n_value is None:
            return None, "no N value"
        inc1 = n_value
        npen = rd.num(row, "ISPT_NPEN")
        if npen is not None and 150 < npen < 450:
            pen = npen - 150
        elif m:
            pen = float(m.group(2))
    total = (inc1 or 0) + (inc2 or 0)
    if total > 400 or (inc1 or 0) > 200 or (inc2 or 0) > 200 or (seat or 0) > 200:
        return None, "more than 200 blows"
    out: Dict[str, Any] = {"depth": round(depth, 2), "seat": int(round(seat or 0)), "inc1": int(round(inc1 or 0)),
                           "inc2": int(round(inc2)) if inc2 is not None else None,
                           "penetration_mm": int(round(pen)) if pen is not None and pen >= 1 else None,
                           "remarks": _ascii(row.get("ISPT_REM"))[:300]}
    return out, None


def _lab_results(gname: str, row: Dict[str, str], rd: _Reader) -> List[Tuple[str, Dict[str, Any]]]:
    """Results of one lab row as [(test_type, results)]."""
    n = rd.num
    out: List[Tuple[str, Dict[str, Any]]] = []
    if gname == "LNMC":
        out.append(("moisture", {"w": n(row, "LNMC_MC")}))
    elif gname == "LLPL":
        ll, pl, pi = n(row, "LLPL_LL"), n(row, "LLPL_PL"), _num(row.get("LLPL_PI"))
        if pi is None and ll is not None and pl is not None:
            pi = round(ll - pl, 2)
        out.append(("atterberg", {"ll": ll, "pl": pl, "pi": pi}))
    elif gname == "GRAG":
        fine = n(row, "GRAG_FINE")
        silt, clay = n(row, "GRAG_SILT"), n(row, "GRAG_CLAY")
        out.append(("grain_size", {"gravel": n(row, "GRAG_GRAV"), "sand": n(row, "GRAG_SAND"), "silt": silt, "clay": clay,
                                   "fines": fine, "cu": _num(row.get("GRAG_UC")), "cc": _num(row.get("GRAG_CC"))}))
    elif gname == "LDEN":
        bden, dden, mc = n(row, "LDEN_BDEN"), n(row, "LDEN_DDEN"), n(row, "LDEN_MC")
        res = {"gamma_bulk": round(bden * 9.81, 2) if bden else None, "gamma_dry": round(dden * 9.81, 2) if dden else None}
        out.append(("moisture", {"w": mc, **res}) if mc is not None else ("density", res))
    elif gname == "LPDN":
        out.append(("specific_gravity", {"gs": n(row, "LPDN_PDEN")}))
    elif gname == "CMPG":
        out.append(("compaction", {"mdd": n(row, "CMPG_MAXD"), "omc": n(row, "CMPG_MCOP")}))
    elif gname == "SHBG":
        out.append(("direct_shear", {"c": n(row, "SHBG_PCOH"), "phi": n(row, "SHBG_PHI")}))
    elif gname == "PTST":
        k = n(row, "PTST_K")
        out.append(("permeability_lab", {"k": float(f"{k * 100:.3e}") if k is not None else None, "e": _num(row.get("PTST_VOID"))}))
    elif gname == "RPLT":
        out.append(("point_load", {"is50": n(row, "RPLT_PLSI")}))
    elif gname == "RELD":
        out.append(("relative_density", {"rho_max": n(row, "RELD_DMAX"), "rho_min": n(row, "RELD_DMIN")}))
    elif gname == "CLSS":  # AGS3 classification
        mc, ll, pl = _num(row.get("CLSS_NMC")), _num(row.get("CLSS_LL")), _num(row.get("CLSS_PL"))
        bden, dden, pd = _num(row.get("CLSS_BDEN")), _num(row.get("CLSS_DDEN")), _num(row.get("CLSS_PD"))
        if mc is not None or bden is not None:
            out.append(("moisture", {"w": mc, "gamma_bulk": round(bden * 9.81, 2) if bden else None,
                                     "gamma_dry": round(dden * 9.81, 2) if dden else None}))
        if ll is not None:
            out.append(("atterberg", {"ll": ll, "pl": pl, "pi": round(ll - pl, 2) if pl is not None else None}))
        if pd is not None:
            out.append(("specific_gravity", {"gs": pd}))
    elif gname == "GCHM":
        code = str(row.get("GCHM_CODE") or row.get("GCHM_NAME") or "").upper().replace(" ", "")
        unit = _unit_key(str(row.get("GCHM_UNIT") or ""))
        value = _num(row.get("GCHM_RESL"))
        water = str(row.get("SAMP_TYPE") or "").upper() == "W" or unit in ("mg/l", "g/l", "ug/l")
        chem: Dict[str, Any] = {}
        if value is not None:
            if code in ("PH",) or code.startswith("PH"):
                chem["ph_water" if water else "ph_soil"] = value
            elif "SO4" in code or "SULPH" in code or "SULF" in code:
                if water:
                    chem["so4_water"] = value * _CONVERSIONS["mg/l"].get(unit, 1)
                elif unit == "%":
                    chem["so4_soil"] = value
                elif unit in ("mg/kg", "ppm"):
                    chem["so4_soil"] = value / 10000
                elif unit == "g/l":
                    chem["so4_soil"] = value / 10  # 2:1 water:soil extract, g/L -> % (BRE SD1 convention)
            elif code in ("CL", "CL-", "CHLORIDE") or code.startswith("CL_") or "CHLORIDE" in code:
                chem["cl_water" if water else "cl_soil"] = value * (_CONVERSIONS["mg/l"].get(unit, 1) if water else
                                                                  (10000 if unit == "%" else 1))
            elif "LOI" in code or "ORG" in code:
                chem["organic"] = value
            elif "RES" in code:
                chem["resistivity"] = value * (100 if unit in ("ohmm", "ohm.m", "ω·m", "ωm") else 1)
        if chem:
            out.append(("chemistry", chem))
    return [(t, {k: v for k, v in r.items() if v is not None}) for t, r in out if any(v is not None for v in r.values())]


def _bound_results(test_type: str, results: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Keeps values the result fields accept; returns (kept, number dropped)."""
    spec = {f.name: f for f in LAB_RESULTS.get(test_type, [])}
    kept: Dict[str, Any] = {}
    dropped = 0
    for name, value in results.items():
        f = spec.get(name)
        if f is None:
            continue
        if f.type in ("number", "int") and isinstance(value, (int, float)):
            if (f.min is not None and value < f.min) or (f.max is not None and value > f.max):
                dropped += 1
                continue
            value = int(round(value)) if f.type == "int" else round(float(value), 6)
        kept[name] = value
    return kept, dropped


def _sample_ref(row: Dict[str, str]) -> str:
    ref = _ascii(row.get("SAMP_REF")) or _ascii(row.get("SAMP_ID"))
    if not ref:
        top = _num(row.get("SAMP_TOP"))
        ref = f"{_ascii(row.get('SAMP_TYPE')) or 'S'}@{_fmt(top, 2)}"
    return ref[:40]


def _lab_key(borehole: str, ref: str, top: Optional[float], test_type: str) -> Tuple[str, str, float, str]:
    return borehole.strip().lower(), ref.strip().upper(), round(float(top or 0), 2), test_type


def build_plan(parsed: Parsed, *, project_name: str = "", include_lab: bool = True, on_duplicate: str = "skip",
               user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    log = _Log()
    log.errors, log.warnings = list(parsed.errors), list(parsed.warnings)
    groups = parsed.groups
    if "LOCA" not in groups or not groups["LOCA"].rows:
        log.error("The file has no LOCA group with boreholes; nothing can be imported.")
    _check_keys(parsed, log)
    readers = {name: _Reader(g, log) for name, g in groups.items()}
    abbr = _abbr(parsed)
    proj = (groups["PROJ"].rows[0] if "PROJ" in groups and groups["PROJ"].rows else {})
    tran = (groups["TRAN"].rows[0] if "TRAN" in groups and groups["TRAN"].rows else {})
    file_project = (proj.get("PROJ_NAME") or proj.get("PROJ_ID") or "").strip()
    project = (project_name or "").strip() or file_project
    if not project:
        project = "Imported project"
        log.warn("The file names no project (PROJ_NAME); the boreholes go to 'Imported project'. Enter a project name to change it.")
    for name, g in groups.items():
        if name not in GROUP_USE:
            log.warn("Group {group} is not imported ({n} rows).", group=name, n=len(g.rows))
    by = {name: _by_loca(groups.get(name)) for name in ("HDPH", "HDIA", "CDIA", "GEOL", "ISPT", "SAMP", "CORE", "WSTG", "WSTD")}
    lab_by = {name: _by_loca(groups.get(name)) for name in LAB_GROUPS if include_lab}
    samp_depth: Dict[Tuple[str, str], Optional[float]] = {}
    for row in groups["SAMP"].rows if "SAMP" in groups else []:
        samp_depth[(row.get("LOCA_ID", "").strip(), _sample_ref(row).upper())] = readers["SAMP"].num(row, "SAMP_BASE")

    role = str((user or {}).get("role") or "general")
    email = str((user or {}).get("email") or "").lower()
    existing_tests: Dict[Tuple[str, str, float, str], Dict[str, Any]] = {}
    if include_lab and lab_by:
        for rec in records.list_records("lab_tests"):
            existing_tests[_lab_key(str(rec.get("borehole_id") or ""), str(rec.get("sample_ref") or ""),
                                    _num(rec.get("depth_top")), str(rec.get("test_type") or ""))] = rec
    lab_entity = ENTITIES["lab_tests"]

    boreholes: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for loca in groups["LOCA"].rows if "LOCA" in groups else []:
        lid = loca.get("LOCA_ID", "").strip()
        messages: List[Msg] = []
        bh: Dict[str, Any] = {"id": lid, "messages": messages}
        if lid.lower() in seen_ids:
            continue
        seen_ids.add(lid.lower())
        rd = readers["LOCA"]
        hdph = sorted(by["HDPH"].get(lid, []), key=lambda r: readers["HDPH"].num(r, "HDPH_TOP") or 0)
        h0 = hdph[0] if hdph else {}
        report: Dict[str, Any] = {"BoreholeID": lid, "ProjectName": project}
        rem = _parse_loca_rem(_ascii(loca.get("LOCA_REM")) if loca.get("LOCA_REM") else "")
        report.update(rem)
        report["SiteName"] = (loca.get("LOCA_LOCA") or proj.get("PROJ_LOC") or project).strip()[:200]
        lat, lon = _dms(loca.get("LOCA_LAT")), _dms(loca.get("LOCA_LON"))
        report["Latitude"] = _fmt(lat) if lat is not None else ""
        report["Longitude"] = _fmt(lon) if lon is not None else ""
        report["GroundElevation_mRL"] = _fmt(rd.num(loca, "LOCA_GL"), 3)
        start = _date(loca.get("LOCA_STAR")) or _date(h0.get("HDPH_STAR"))
        if not start:
            start = _date(tran.get("TRAN_DATE")) or local_today().isoformat()
            messages.append(msg("No start date (LOCA_STAR); {date} is used.", date=start))
        end = _date(loca.get("LOCA_ENDD")) or max([_date(r.get("HDPH_ENDD")) for r in hdph] + [""]) or start
        report["StartDate"], report["EndDate"] = start, end
        method = (h0.get("HDPH_METH") or "").strip()
        if not method:
            code = (h0.get("HDPH_TYPE") or loca.get("LOCA_TYPE") or "").strip().upper()
            method = METHOD_BY_CODE.get(code) or abbr.get(("LOCA_TYPE", code)) or abbr.get(("HDPH_TYPE", code)) or code
        if not method:
            method = "Not recorded"
            messages.append(msg("No drilling method in the file; 'Not recorded' is used."))
        report["DrillingMethod"] = method[:100]
        report["DrillRig"] = (h0.get("HDPH_EXC") or "").strip()[:100]
        size = (h0.get("HDPH_BTYP") or "").strip().split(" ")[0].upper()
        if size in CORE_SIZES:
            report["CoreSize"] = size
        report["LoggingGeologist"] = (h0.get("HDPH_LOG") or "").strip()[:200]
        contractor = (h0.get("HDPH_CONT") or proj.get("PROJ_CONT") or "").strip()
        if not contractor:
            contractor = "Not recorded"
            messages.append(msg("No contractor (HDPH_CONT or PROJ_CONT); 'Not recorded' is used."))
        report["Contractor"] = contractor[:200]
        final = rd.num(loca, "LOCA_FDEP")
        if final is None:
            candidates = [readers[g].num(r, h) for g, h in (("HDPH", "HDPH_BASE"), ("GEOL", "GEOL_BASE"), ("CORE", "CORE_BASE"))
                          for r in by[g].get(lid, [])]
            known = [c for c in candidates if c is not None]
            final = max(known) if known else None
            if final is not None:
                messages.append(msg("No final depth (LOCA_FDEP); the deepest stratum or hole depth is used."))
        report["FinalDepth_m"] = _fmt(final, 2) if final is not None else ""
        hdia = sorted(by["HDIA"].get(lid, []), key=lambda r: readers["HDIA"].num(r, "HDIA_DPTH") or 0)
        if hdia and not str(hdia[-1].get("HDIA_REM") or "").startswith("Nominal"):
            report["BoreholeDiameter_mm"] = _fmt(readers["HDIA"].num(hdia[-1], "HDIA_DIAM"), 1)
        cdia = sorted(by["CDIA"].get(lid, []), key=lambda r: readers["CDIA"].num(r, "CDIA_DPTH") or 0)
        if cdia:
            report["CasingInstalled_mm"] = _fmt(readers["CDIA"].num(cdia[-1], "CDIA_DIAM"), 1)
        strikes = [readers["WSTG"].num(r, "WSTD_POST") or readers["WSTG"].num(r, "WSTG_DPTH") for r in by["WSTG"].get(lid, [])]
        rest = [readers["WSTD"].num(r, "WSTD_POST") for r in by["WSTD"].get(lid, [])] if "WSTD" in readers else []
        levels = [v for v in (rest or strikes) if v is not None]
        report["GroundwaterEncountered"] = "True" if levels or strikes else "False"
        report["GroundwaterDepth_m"] = _fmt(min(levels), 2) if levels else ""
        bh["groundwater"] = min(levels) if levels else None
        try:
            clean_report = Report.model_validate(report).model_dump()
        except ValidationError as exc:
            messages.append(msg("Log refused: {why}", why=_first_error(exc)))
            clean_report = None

        # Depth data
        depth: Dict[str, List[Dict[str, Any]]] = {"layers": [], "spt": [], "samples": [], "core": []}
        g_r = readers.get("GEOL")
        for row in by["GEOL"].get(lid, []):
            assert g_r is not None
            top, base = g_r.num(row, "GEOL_TOP"), g_r.num(row, "GEOL_BASE")
            if top is None or base is None:
                messages.append(msg("Line {line} (GEOL): stratum without top or base; skipped.", line=row["_line"]))
                continue
            rem_text = str(row.get("GEOL_REM") or "")
            m = re.search(r"USCS:\s*([A-Za-z0-9/\-]{1,20})", rem_text) or re.search(r"\((" + _USCS + r")\)", str(row.get("GEOL_DESC") or ""))
            depth["layers"].append({"top": top, "base": base, "uscs": m.group(1).upper() if m else "",
                                    "description": str(row.get("GEOL_DESC") or "").strip()[:1000]})
        s_r = readers.get("ISPT")
        n_only = 0
        for row in by["ISPT"].get(lid, []):
            assert s_r is not None
            test, why = _spt(row, s_r)
            if test is None:
                messages.append(msg("Line {line} (ISPT): SPT skipped ({why}).", line=row["_line"], why=why))
                continue
            if test["inc2"] is None and test["penetration_mm"] is None:
                n_only += 1
            depth["spt"].append(test)
        if n_only:
            messages.append(msg("{n} SPT tests give only N (no increments); N is kept as the first increment.", n=n_only))
        sm_r = readers.get("SAMP")
        refs: set = set()
        skipped_types: set = set()
        for row in by["SAMP"].get(lid, []):
            assert sm_r is not None
            top = sm_r.num(row, "SAMP_TOP")
            code = str(row.get("SAMP_TYPE") or "").strip().upper()
            code = SAMPLE_TYPE_ALIASES.get(code, code)
            if top is None or code not in details.SAMPLE_TYPES:
                skipped_types.add(code or "?")
                continue
            ref = _ascii(row.get("SAMP_REF"))[:20]
            base = sm_r.num(row, "SAMP_BASE")
            if ref and ref.upper() in refs:
                ref = (ref[:14] + "-" + _fmt(top, 2))[:20]
            if ref:
                refs.add(ref.upper())
            depth["samples"].append({"top": top, "base": base if base is not None and base > top else None, "type": code,
                                     "ref": ref, "remarks": _ascii(row.get("SAMP_REM"))[:300]})
        if skipped_types:
            messages.append(msg("Samples of type {types} are not imported (the app keeps the AGS4 types U, UT, TW, P, D, B, "
                                "SPTLS, C, W).", types=", ".join(sorted(skipped_types))))
        c_r = readers.get("CORE")
        for row in by["CORE"].get(lid, []):
            assert c_r is not None
            top, base = c_r.num(row, "CORE_TOP"), c_r.num(row, "CORE_BASE")
            if top is None or base is None:
                continue
            depth["core"].append({"top": top, "base": base, "tcr": c_r.num(row, "CORE_PREC"), "scr": c_r.num(row, "CORE_SREC"),
                                  "rqd": c_r.num(row, "CORE_RQD"), "remarks": _ascii(row.get("CORE_REM"))[:300]})
        present = {k for k, g in (("layers", "GEOL"), ("spt", "ISPT"), ("samples", "SAMP"), ("core", "CORE")) if g in groups}
        depth_ok = True
        try:
            details.DetailsIn.model_validate(depth)
        except ValidationError as exc:
            messages.append(msg("Depth data refused: {why}", why=_first_error(exc)))
            depth_ok = False

        # Laboratory results, one record per sample and test.
        lab: Dict[Tuple[str, float, str], Dict[str, Any]] = {}
        dropped = 0
        for gname, rows_by in lab_by.items():
            for row in rows_by.get(lid, []):
                ref = _sample_ref(row)
                top = _num(row.get("SAMP_TOP"))
                if top is None:
                    continue
                for test_type, res in _lab_results(gname, row, readers[gname]):
                    kept, lost = _bound_results(test_type, res)
                    dropped += lost
                    if not kept:
                        continue
                    key = (ref.upper(), round(top, 2), test_type)
                    entry = lab.setdefault(key, {"sample_ref": ref, "depth_top": round(top, 2),
                                                 "depth_base": samp_depth.get((lid, ref.upper())), "test_type": test_type,
                                                 "results": {}, "values": {}, "standard": ""})
                    for name, value in kept.items():
                        entry["values"].setdefault(name, []).append(value)
                    meth = str(row.get(f"{gname}_METH") or "").strip()
                    if meth and not entry["standard"]:
                        entry["standard"] = meth[:300]
        for entry in lab.values():
            for name, vals in entry.pop("values").items():
                nums = [v for v in vals if isinstance(v, (int, float))]
                entry["results"][name] = round(sum(nums) / len(nums), 4) if len(nums) == len(vals) and len(nums) > 1 else vals[-1]
        if dropped:
            messages.append(msg("{n} laboratory values outside the accepted range were left out.", n=dropped))

        exists = storage.get_report(lid)
        can_edit = exists is not None and (role in ("admin", "manager")
                                           or str(exists.get("SubmittedBy") or "").strip().lower() == email)
        if clean_report is None or not depth_ok or final is None:
            if final is None:
                messages.append(msg("No final depth in the file (LOCA_FDEP)."))
            action = "error"
        elif exists is None:
            action = "create"
        elif on_duplicate == "overwrite" and can_edit:
            action = "overwrite"
        else:
            action = "skip"
            if on_duplicate == "overwrite" and not can_edit:
                messages.append(msg("Only the person who submitted this log, a manager or an admin can overwrite it."))
        lab_rows = []
        for entry in lab.values():
            prev = existing_tests.get(_lab_key(exists["BoreholeID"] if exists else lid, entry["sample_ref"], entry["depth_top"],
                                               entry["test_type"]))
            if prev is None:
                entry["action"] = "create" if action in ("create", "overwrite", "skip") and records.can_write(lab_entity, role, None, email) else "skip"
            elif on_duplicate == "overwrite" and records.can_write(lab_entity, role, prev, email):
                entry["action"], entry["record_id"] = "overwrite", prev["id"]
            else:
                entry["action"] = "skip"
            if action == "error":
                entry["action"] = "skip"
            lab_rows.append(entry)
        bh.update({
            "status": "error" if action == "error" else ("exists" if exists else "new"),
            "action": action,
            "existing_id": exists["BoreholeID"] if exists else None,
            "report": clean_report,
            "depth": depth,
            "replace": sorted(present),
            "layers": len(depth["layers"]), "spt": len(depth["spt"]), "samples": len(depth["samples"]), "core": len(depth["core"]),
            "lab": lab_rows,
        })
        boreholes.append(bh)

    used = []
    for name, g in groups.items():
        use = GROUP_USE.get(name, "Not imported")
        if name in LAB_GROUPS and not include_lab:
            use = "Not imported"
        used.append({"group": name, "rows": len(g.rows), "use": use})
    totals = {a: sum(1 for b in boreholes if b["action"] == a) for a in ("create", "overwrite", "skip", "error")}
    totals["lab_create"] = sum(1 for b in boreholes for e in b["lab"] if e["action"] == "create")
    totals["lab_overwrite"] = sum(1 for b in boreholes for e in b["lab"] if e["action"] == "overwrite")
    if log.dropped:
        log.warnings.append(msg("{n} more messages are not shown.", n=log.dropped))
    return {
        "format": parsed.fmt,
        "edition": (tran.get("TRAN_AGS") or "").strip(),
        "producer": (tran.get("TRAN_PROD") or "").strip(),
        "project": {"file": file_project, "used": project},
        "groups": used,
        "errors": log.errors,
        "warnings": log.warnings,
        "boreholes": boreholes,
        "totals": totals,
        "can_import": bool(totals["create"] or totals["overwrite"] or totals["lab_create"] or totals["lab_overwrite"]),
    }


def public_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """The preview for the browser: counts and messages, not the full rows."""
    out = {k: v for k, v in plan.items() if k != "boreholes"}
    out["boreholes"] = [{
        "id": b["id"], "status": b["status"], "action": b["action"], "messages": b["messages"],
        "layers": b.get("layers", 0), "spt": b.get("spt", 0), "samples": b.get("samples", 0), "core": b.get("core", 0),
        "groundwater": b.get("groundwater"),
        "lab": sum(1 for e in b.get("lab", []) if e["action"] != "skip"),
        "lab_total": len(b.get("lab", [])),
    } for b in plan["boreholes"]]
    return out


# --------------------------------------------------------------------------- #
# 3. Apply
# --------------------------------------------------------------------------- #

def apply(plan: Dict[str, Any], user: Dict[str, Any], filename: str = "") -> Dict[str, Any]:
    email = str(user.get("email") or "")
    done: Dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "lab_created": 0, "lab_updated": 0}
    problems: List[Msg] = []
    projects = {str(p.get("name") or "").strip().lower(): p.get("id") for p in records.list_records("projects")}
    note = f"AGS4 import: {_ascii(filename)[:120]}" if filename else "AGS4 import"
    for bh in plan["boreholes"]:
        action = bh["action"]
        if action in ("skip", "error"):
            done["skipped" if action == "skip" else "failed"] += 1
        else:
            try:
                target = _store_borehole(bh, action, email)
            except (storage.DuplicateReportError, details.ConflictError, ValueError) as exc:
                problems.append(msg("{id}: not imported ({why})", id=bh["id"], why=str(exc)))
                done["failed"] += 1
                continue
            done["created" if action == "create" else "updated"] += 1
            audit.record(email, "log.imported", target, {"strata": bh["layers"], "spt": bh["spt"], "samples": bh["samples"],
                                                         "core": bh["core"], "mode": action})
        if action == "error":
            continue
        borehole = bh.get("existing_id") or bh["id"]
        project_id = projects.get(str((bh.get("report") or {}).get("ProjectName") or "").strip().lower())
        for entry in bh["lab"]:
            if entry["action"] == "skip":
                continue
            data: Dict[str, Any] = {"borehole_id": borehole, "sample_ref": entry["sample_ref"], "depth_top": entry["depth_top"],
                                    "test_type": entry["test_type"], "status": "done", "results": entry["results"]}
            if entry.get("depth_base") is not None and entry["depth_base"] > entry["depth_top"]:
                data["depth_base"] = entry["depth_base"]
            if project_id:
                data["project_id"] = project_id
            try:
                if entry["action"] == "overwrite":
                    prev = records.get_record("lab_tests", entry["record_id"])
                    merged = {k: v for k, v in prev.items() if not k.startswith("_")}
                    merged["results"] = {**(prev.get("results") or {}), **entry["results"]}
                    merged["status"] = "done"
                    records.save("lab_tests", merged, email, record_id=entry["record_id"])
                    done["lab_updated"] += 1
                else:
                    data["remarks"] = note
                    if entry.get("standard"):
                        data["standard"] = entry["standard"]
                    records.save("lab_tests", data, email)
                    done["lab_created"] += 1
            except (records.RecordError, records.ConflictError, records.NotFound) as exc:
                problems.append(msg("{id} {sample}: laboratory result not imported ({why})", id=borehole,
                                    sample=entry["sample_ref"], why=str(exc)))
    return {**done, "problems": problems[:MAX_MESSAGES]}


def _store_borehole(bh: Dict[str, Any], action: str, email: str) -> str:
    report = dict(bh["report"])
    with docstore.lock(storage.DOC):
        if action == "create":
            storage.save_report(report, submitted_by=email)
            details.delete_details(report["BoreholeID"])
            target = report["BoreholeID"]
            current: Dict[str, Any] = {}
        else:
            target = bh["existing_id"]
            updates = {k: v for k, v in report.items() if k in storage.EDITABLE_FIELDS}
            if storage.update_report(target, updates) is None:
                raise ValueError("the log no longer exists")
            current = details.get_details(target)
        merged = {k: (bh["depth"][k] if k in bh["replace"] else current.get(k, [])) for k in ("layers", "spt", "samples", "core")}
        if any(merged.values()) or current:
            payload = details.DetailsIn.model_validate(merged)
            details.save_details(target, payload, email)
    return str(target)


def run(text: str, *, project_name: str = "", include_lab: bool = True, on_duplicate: str = "skip",
        user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Parse and plan in one step (used by the preview and the import)."""
    if on_duplicate not in ("skip", "overwrite"):
        raise AGSImportError("Choose skip or overwrite for boreholes that already exist")
    return build_plan(parse(text), project_name=project_name, include_lab=include_lab, on_duplicate=on_duplicate, user=user)

