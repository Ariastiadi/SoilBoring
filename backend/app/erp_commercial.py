"""Commercial ERP calculations (blueprint A.1).

* Project difficulty index and risk premium (A.1.3): 16 factors scored 1–5, weighted average,
  rounded to an index 1–5, looked up in the risk premium table.
* Pricing & Budgeting Decision, PBD (A.1.1, A.1.4): project cost budget (ABP) from budget lines
  priced at the unit cost (HPJ) of the price list, risk premium and margin on the ABP, bid price,
  minimum client price, ratio ABP / revenue.
* Conversion to client rates (A.1.5): quotation items from an approved PBD.
* Client decision (A.1.2), weekly work plan and budget drawdown (A.1.6), bank guarantees and
  SKBDN (A.1.9), client card, receivable aging and NPAR (A.1.10–A.1.12), commercial overview
  for the management dashboard (A.1.14).

The functions work on plain records (dicts) and never read the store themselves: the hooks in
entities_commercial.py and the router pass in what they need. Labels are English; the
interface translates them. Money is IDR; percentages are given as 0–100.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .calcbase import axis, chart, result, series, table

Rec = Dict[str, Any]


class CommercialError(ValueError):
    """Input that cannot be stored; the message is shown to the user."""


# --------------------------------------------------------------------------- #
# Regions: provinces and the region zones of the blueprint ("ZONA WILAYAH")
# --------------------------------------------------------------------------- #

PROVINCES: List[Tuple[str, str]] = [
    ("AC", "Aceh"), ("SU", "Sumatera Utara"), ("SB", "Sumatera Barat"), ("RI", "Riau"), ("KR", "Kepulauan Riau"),
    ("JA", "Jambi"), ("SS", "Sumatera Selatan"), ("BB", "Kepulauan Bangka Belitung"), ("BE", "Bengkulu"),
    ("LA", "Lampung"), ("JK", "DKI Jakarta"), ("JB", "Jawa Barat"), ("BT", "Banten"), ("JT", "Jawa Tengah"),
    ("YO", "DI Yogyakarta"), ("JI", "Jawa Timur"), ("BA", "Bali"), ("NB", "Nusa Tenggara Barat"),
    ("NT", "Nusa Tenggara Timur"), ("KB", "Kalimantan Barat"), ("KT", "Kalimantan Tengah"),
    ("KS", "Kalimantan Selatan"), ("KI", "Kalimantan Timur"), ("KU", "Kalimantan Utara"), ("SA", "Sulawesi Utara"),
    ("GO", "Gorontalo"), ("ST", "Sulawesi Tengah"), ("SR", "Sulawesi Barat"), ("SN", "Sulawesi Selatan"),
    ("SG", "Sulawesi Tenggara"), ("MA", "Maluku"), ("MU", "Maluku Utara"), ("PA", "Papua"), ("PB", "Papua Barat"),
    ("PD", "Papua Barat Daya"), ("PS", "Papua Selatan"), ("PT", "Papua Tengah"), ("PE", "Papua Pegunungan"),
]
PROVINCE_NAME = dict(PROVINCES)

# (zone, number, provinces as written in the blueprint, index 1–5, province codes)
ZONES: List[Tuple[str, int, str, int, Tuple[str, ...]]] = [
    ("A", 1, "Banten, Jawa Barat", 1, ("BT", "JB")),
    ("B", 2, "DKI Jakarta (incl. the airport area)", 1, ("JK",)),
    ("C", 3, "Jawa Tengah, Jawa Timur, DI Yogyakarta", 1, ("JT", "JI", "YO")),
    ("D", 4, "South Sumatra (Sumatera Selatan, Bengkulu, Bangka Belitung, Lampung)", 2, ("SS", "BE", "BB", "LA")),
    ("E", 5, "Central Sumatra (Sumatera Barat, Riau, Jambi)", 2, ("SB", "RI", "JA")),
    ("F", 6, "North Sumatra (Sumatera Utara, Aceh)", 2, ("SU", "AC")),
    ("G", 7, "Bali, NTB, NTT", 3, ("BA", "NB", "NT")),
    ("H", 8, "Kepulauan Riau", 3, ("KR",)),
    ("I", 9, "Kalimantan Barat, Kalimantan Selatan, Kalimantan Timur", 4, ("KB", "KS", "KI")),
    ("J", 10, "Kalimantan Tengah, Kalimantan Utara", 4, ("KT", "KU")),
    # Sulawesi Tenggara is not in the blueprint table; placed with its neighbours in zone K.
    ("K", 11, "Sulawesi Selatan, Sulawesi Tengah, Sulawesi Barat", 4, ("SN", "ST", "SR", "SG")),
    ("L", 12, "Sulawesi Utara, Gorontalo", 5, ("SA", "GO")),
    ("M", 13, "Maluku, Maluku Utara", 5, ("MA", "MU")),
    # The provinces formed from Papua and Papua Barat since 2022 stay in zone N.
    ("N", 14, "Papua, Papua Barat", 5, ("PA", "PB", "PD", "PS", "PT", "PE")),
]
ZONE_INDEX: Dict[str, int] = {z[0]: z[3] for z in ZONES}
PROVINCE_ZONE: Dict[str, str] = {code: z[0] for z in ZONES for code in z[4]}
ZONE_OPTIONS: List[Tuple[str, str]] = [(z[0], f"Zone {z[0]}: {z[2]}") for z in ZONES]


# --------------------------------------------------------------------------- #
# Company defaults (used while company settings leave the tables empty)
# --------------------------------------------------------------------------- #

def _f(key: str, factor: str, levels: Sequence[str], weight: float = 1.0) -> Rec:
    return {"key": key, "factor": factor, "weight": weight, "levels": list(levels)}


# The 16 factors of the blueprint's "Indeks Kesulitan Proyek" sheet with its level descriptions
# (1 very easy … 5 very difficult). Equal weights: the sheet takes the plain aggregate.
DEFAULT_FACTORS: List[Rec] = [
    _f("zone", "Region zone", ["Zone A–C (Java and Jakarta)", "Zone D–F (Sumatra)", "Zone G–H (Bali, Nusa Tenggara, Riau Islands)",
                               "Zone I–K (Kalimantan, Sulawesi)", "Zone L–N (North Sulawesi, Gorontalo, Maluku, Papua)"]),
    _f("access", "Road access to the site", ["Paved road to the site", "Good road, short unpaved stretch",
                                              "Unpaved road, passable in the dry season", "Off-road: 4×4, track or river crossing",
                                              "No road: on foot, by boat or by air"]),
    _f("rig_move", "Time to move the rig to the boring points", ["1–3 days", "3–7 days", "7–10 days", "10–14 days", "More than 14 days"]),
    _f("settlement", "Distance to the nearest settlement", ["Less than 1 km", "1–2 km", "2–3 km", "3–5 km", "More than 5 km"]),
    _f("location", "Work location", ["Open area, fenced", "Around existing buildings", "Coast or swamp",
                                      "Oil and gas or industrial area, coast, swamp", "Forest, plantation or mountains"]),
    _f("spread", "Spread of the work", ["One area", "Split over 2 areas", "Split over 3 areas", "Split over 4 areas",
                                         "Split over more than 4 areas"]),
    _f("soil", "Soil layers", ["Very soft to soft soil", "Medium soil", "Hard soil, gravel, or soil with rock",
                                "Gravel and rock strata", "Rock strata throughout"]),
    _f("water_depth", "Water depth to the seabed (over-water work)", ["None (on land)", "1–5 m", "5–10 m", "10–15 m", "More than 15 m"]),
    _f("depth", "Drilling depth", ["Up to 30 m", "31–60 m", "61–80 m", "81–100 m", "More than 100 m"]),
    _f("hse", "HSE requirements", ["None, or the company's own HSE procedure", "Local site rules", "Industrial estate rules",
                                    "HSE standard of an EPC contractor", "Oil and gas or mining HSE standard"]),
    _f("land", "Land status", ["Owned by the client, cleared", "Owned by the client", "Owned by the client or not yet cleared",
                                "Not yet cleared, access through third parties", "Not yet cleared, access disputed"]),
    _f("water", "Water supply for drilling", ["Easy, at the site", "Easy, close by", "Easy to difficult", "Difficult, trucked in",
                                               "Very difficult"]),
    _f("ground", "Ground conditions", ["Flat, dry and firm", "Flat and dry", "Flat and waterlogged",
                                        "Flat, dry to waterlogged, or shallow nearshore (< 8 m)",
                                        "Hilly, slopes, river, or deep offshore (> 8 m)"]),
    _f("utilities", "Underground facilities (pipes, cables)", ["None", "None known", "None expected, to be checked",
                                                               "May be present", "Present (live services)"]),
    _f("permits", "Medical check-up, work permits, safety and security", ["Easy", "Easy, standard induction", "Moderate", "Strict",
                                                                          "Very strict"]),
    _f("allocation", "Project allocation (share of the company's crews and rigs tied up)", ["None", "Partly", "About half", "Mostly",
                                                                                            "Fully"]),
]

# "Kompensasi Index Kesulitan": index → risk premium (% of the project cost budget).
DEFAULT_PREMIUMS: Dict[int, float] = {1: 5.0, 2: 8.0, 3: 11.0, 4: 14.0, 5: 17.0}

# Approval authority of the pricing committee by bid value (the blueprint's PBD sheet).
DEFAULT_APPROVAL_LIMITS: List[Tuple[Optional[float], str]] = [
    (2e9, "Approver 1"), (5e9, "Approvers 1 and 2"), (10e9, "Approvers 1, 2 and 3"), (None, "Approvers 1 to 4"),
]

DEFAULT_MAX_COST_RATIO = 75.0   # ABP / project revenue, %
DEFAULT_MARGIN = 30.0           # % of the ABP
DEFAULT_NPAR_DAYS = 90          # days since the invoice date
DEFAULT_PAYMENT_DAYS = 30       # due date when an invoice has none
DEFAULT_GUARANTEE_WARNING_DAYS = 30

SECTIONS: List[Tuple[str, str]] = [
    ("work", "Work items (price list)"), ("pre_project", "Pre-project (solicitation) cost"), ("labour", "Labour"),
    ("accommodation", "Accommodation and per diem"), ("operations", "Operations"), ("equipment", "Equipment"),
    ("consumables", "Consumables"), ("subcontract", "Subcontract"), ("mobilisation", "Mobilisation"),
    ("demobilisation", "Demobilisation"), ("other", "Other"),
]
SECTION_LABEL = dict(SECTIONS)
MOB_SECTIONS = ("mobilisation", "demobilisation")


def num(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def idr(value: float) -> int:
    """Whole rupiah, half up."""
    return int(math.floor(value + 0.5))


def round_up(value: float, step: float) -> float:
    return float(math.ceil(value / step - 1e-9) * step) if step > 0 else value


def pct(part: float, whole: float, digits: int = 2) -> Optional[float]:
    return round(part / whole * 100, digits) if whole else None


def check(level: str, text: str, **values: Any) -> Rec:
    """A remark shown with the record. ``text`` is a fixed English sentence with {placeholders}
    (translated in the interface); a placeholder ending in ``_idr`` is shown as money."""
    return {"level": level, "text": text, "vars": values}


def parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Company settings with defaults
# --------------------------------------------------------------------------- #

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30] or "factor"


def effective_factors(settings: Optional[Rec]) -> List[Rec]:
    rows = [r for r in (settings or {}).get("difficulty_factors") or [] if str(r.get("factor") or "").strip()]
    if not rows:
        return copy.deepcopy(DEFAULT_FACTORS)
    out = []
    for r in rows:
        weight = num(r.get("weight"))
        out.append({"key": str(r.get("key") or "").strip() or _slug(str(r["factor"])), "factor": str(r["factor"]).strip(),
                    "weight": 1.0 if weight is None else weight,
                    "levels": [str(r.get(f"level_{i}") or "") for i in range(1, 6)]})
    return out


def premium_table(settings: Optional[Rec]) -> Dict[int, float]:
    table_ = dict(DEFAULT_PREMIUMS)
    for r in (settings or {}).get("risk_premium_table") or []:
        index, premium = num(r.get("index")), num(r.get("premium_pct"))
        if index is not None and premium is not None and 1 <= int(index) <= 5:
            table_[int(index)] = premium
    return table_


def approval_limits(settings: Optional[Rec]) -> List[Tuple[Optional[float], str]]:
    rows = [r for r in (settings or {}).get("approval_limits") or [] if str(r.get("level") or "").strip()]
    if not rows:
        return list(DEFAULT_APPROVAL_LIMITS)
    limits = [(num(r.get("up_to")), str(r["level"]).strip()) for r in rows]
    # Rows with a limit from small to large; a row without a limit is the top level.
    return sorted([x for x in limits if x[0] is not None], key=lambda x: x[0] or 0) + [x for x in limits if x[0] is None]


def config(settings: Optional[Rec]) -> Rec:
    s = settings or {}

    def value(name: str, default: float) -> float:
        v = num(s.get(name))
        return default if v is None else v

    return {
        "factors": effective_factors(s),
        "factors_source": "settings" if any(str(r.get("factor") or "").strip() for r in s.get("difficulty_factors") or []) else "default",
        "premiums": [{"index": k, "premium_pct": v} for k, v in sorted(premium_table(s).items())],
        "premiums_source": "settings" if s.get("risk_premium_table") else "default",
        "approval_limits": [{"up_to": a, "level": b} for a, b in approval_limits(s)],
        "max_cost_ratio_pct": value("max_cost_ratio_pct", DEFAULT_MAX_COST_RATIO),
        "default_margin_pct": value("default_margin_pct", DEFAULT_MARGIN),
        "npar_days": int(value("npar_days", DEFAULT_NPAR_DAYS)),
        "payment_days": int(value("default_payment_days", DEFAULT_PAYMENT_DAYS)),
        "guarantee_warning_days": int(value("guarantee_warning_days", DEFAULT_GUARANTEE_WARNING_DAYS)),
        "zones": [{"zone": z[0], "no": z[1], "provinces": z[2], "index": z[3], "codes": list(z[4])} for z in ZONES],
        "province_zone": dict(PROVINCE_ZONE),
        "provinces": [list(p) for p in PROVINCES],
        "sections": [list(s_) for s_ in SECTIONS],
    }


def approval_level(value: Optional[float], settings: Optional[Rec]) -> str:
    if not value:
        return ""
    for limit, level in approval_limits(settings):
        if limit is None or value < limit:
            return level
    return approval_limits(settings)[-1][1]


# --------------------------------------------------------------------------- #
# A.1.3 Project difficulty index → risk premium
# --------------------------------------------------------------------------- #

def difficulty(rows: Iterable[Rec], factors: List[Rec], zone: str = "") -> Rec:
    """Weighted average of the scores (1–5) and the index: the average rounded half up.
    The zone factor takes the index of the region zone when the zone is known."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    by_key = {str(r.get("key") or ""): r for r in rows if r.get("key")}
    by_name = {str(r.get("factor") or "").strip().lower(): r for r in rows}
    lines: List[Rec] = []
    seen = set()
    for f in factors:
        row = by_key.get(f["key"]) or by_name.get(f["factor"].lower())
        if row is not None:
            seen.add(id(row))
        score = num((row or {}).get("score"))
        if f["key"] == "zone" and zone in ZONE_INDEX:
            score = float(ZONE_INDEX[zone])
        lines.append({"key": f["key"], "factor": f["factor"], "weight": f["weight"],
                      "score": None if score is None else max(1.0, min(5.0, score)), "note": (row or {}).get("note") or ""})
    # Rows of factors no longer in the company list keep counting with weight 1.
    for r in rows:
        if id(r) not in seen and num(r.get("score")) is not None:
            lines.append({"key": r.get("key") or "", "factor": r.get("factor") or r.get("key") or "", "weight": 1.0,
                          "score": max(1.0, min(5.0, float(r["score"]))), "note": r.get("note") or ""})
    scored = [x for x in lines if x["score"] is not None and x["weight"] > 0]
    total_w = sum(x["weight"] for x in scored)
    # The zone scores itself; without any other factor scored there is no index yet.
    if not [x for x in scored if x["key"] != "zone"] or total_w <= 0:
        return {"score": None, "index": None, "scored": 0, "total": len(factors), "lines": lines}
    avg = round(sum(x["weight"] * x["score"] for x in scored) / total_w, 6)
    index = max(1, min(5, int(math.floor(avg + 0.5))))
    return {"score": math.floor(avg * 100 + 0.5) / 100, "index": index, "scored": len(scored), "total": len(factors), "lines": lines}


# --------------------------------------------------------------------------- #
# A.1.1 / A.1.4 Pricing & Budgeting Decision
# --------------------------------------------------------------------------- #

def _units(row: Rec) -> float:
    days = num(row.get("days"))
    return (num(row.get("qty")) or 0.0) * (days if days is not None else 1.0)


def pbd_compute(record: Rec, rates: Dict[str, Rec], settings: Optional[Rec], project: Optional[Rec]) -> None:
    cfg = config(settings)
    if project:
        record["client_id"] = project.get("client_id") or ""
        if not record.get("province") and project.get("province"):
            record["province"] = project["province"]
        if not record.get("location") and project.get("location"):
            record["location"] = project["location"]
    if not record.get("zone") and record.get("province") in PROVINCE_ZONE:
        record["zone"] = PROVINCE_ZONE[record["province"]]
    if record.get("scope") == "full" and not record.get("services"):
        record["services"] = ["geotechnical", "topography", "laboratory"]

    diff = difficulty(record.get("difficulty") or [], cfg["factors"], str(record.get("zone") or ""))
    record["difficulty"] = [{"key": x["key"], "factor": x["factor"], "score": x["score"], "note": x["note"]} for x in diff["lines"]]
    record["difficulty_score"] = diff["score"]
    record["difficulty_index"] = diff["index"]
    premiums = premium_table(settings)
    table_pct = premiums.get(diff["index"]) if diff["index"] else None
    override = num(record.get("risk_pct_override"))
    risk_pct = override if override is not None else table_pct
    record["risk_premium_pct"] = risk_pct
    if num(record.get("margin_pct")) is None:
        record["margin_pct"] = cfg["default_margin_pct"]
    margin_pct = float(record["margin_pct"])
    checks: List[Rec] = []

    # Budget lines: a line from the price list without a unit cost takes the rate's HPJ.
    groups: Dict[str, float] = {}
    line_rows: List[List[Any]] = []
    missing: List[str] = []
    abp = min_price = list_value = 0.0
    for row in record.get("costs") or []:
        rate = rates.get(str(row.get("rate_id") or ""))
        if rate and num(row.get("unit_cost")) is None and num(rate.get("cost_unit")) is not None:
            row["unit_cost"] = rate["cost_unit"]
        unit_cost = num(row.get("unit_cost"))
        units = _units(row)
        if unit_cost is None:
            missing.append(str((rate or {}).get("code") or row.get("description") or "?"))
            unit_cost = 0.0
        amount = units * unit_cost
        abp += amount
        section = str(row.get("section") or "other")
        groups[section] = groups.get(section, 0.0) + amount
        if rate and num(rate.get("min_price")):
            min_price += units * float(rate["min_price"])
        else:
            min_price += amount
        if rate and num(rate.get("price")):
            list_value += units * float(rate["price"])
        line_rows.append([SECTION_LABEL.get(section, section), row.get("description") or "", num(row.get("qty")),
                          num(row.get("days")), row.get("unit") or "", idr(unit_cost), idr(amount)])

    abp_i = idr(abp)
    r = risk_pct or 0.0
    risk_amount = idr(abp * r / 100)
    margin_amount = idr(abp * margin_pct / 100)
    raw = abp_i + risk_amount + margin_amount
    step = float(record.get("rounding") or 1000)
    bid = round_up(raw, step) if raw > 0 else 0.0
    tax_pct = num(record.get("tax_pct"))
    tax_pct = 11.0 if tax_pct is None else tax_pct
    vat = idr(bid * tax_pct / 100)
    ratio = pct(abp_i, bid)
    record.update({
        "abp": float(abp_i), "risk_amount": float(risk_amount), "margin_amount": float(margin_amount),
        "bid_price": bid, "bid_with_vat": float(bid + vat), "min_client_price": float(idr(min_price)),
        "price_list_value": float(idr(list_value)) if list_value else None,
        "cost_ratio_pct": ratio, "max_cost_ratio_pct": cfg["max_cost_ratio_pct"],
        "approval_level": approval_level(bid, settings),
    })

    if diff["index"] is None:
        checks.append(check("warn", "Score the difficulty factors to set the risk premium."))
    elif diff["scored"] < diff["total"]:
        checks.append(check("info", "{n} of {total} difficulty factors are scored.", n=diff["scored"], total=diff["total"]))
    if override is not None and table_pct is not None and abs(override - table_pct) > 1e-9:
        checks.append(check("info", "The risk premium was set by the committee at {set}% instead of {table}% from the difficulty index.",
                            set=override, table=table_pct))
    if not record.get("costs"):
        checks.append(check("warn", "Add the cost budget lines."))
    if missing:
        checks.append(check("warn", "No unit cost for: {items}. Enter it, or complete the rate build-up in the price list.",
                            items=", ".join(missing[:8])))
    if bid and bid < min_price - 0.5:
        checks.append(check("error", "The bid price is below the minimum client price."))
    if ratio is not None and ratio > cfg["max_cost_ratio_pct"]:
        checks.append(check("warn", "The cost ratio ABP/revenue of {ratio}% is above the company maximum of {max}%.",
                            ratio=ratio, max=cfg["max_cost_ratio_pct"]))
    if record.get("costs") and not any(str(c.get("section")) in MOB_SECTIONS for c in record["costs"]):
        checks.append(check("info", "No mobilisation or demobilisation line: the quotation must state that it is excluded."))
    if not num(record.get("duration_weeks")):
        checks.append(check("info", "Enter the duration in weeks; the weekly work plan is checked against it."))
    record["checks"] = checks

    group_rows = [[label, idr(groups[key]), pct(groups[key], abp) or 0.0] for key, label in SECTIONS if key in groups]
    build: List[List[Any]] = [
        ["Total project cost budget (ABP)", None, abp_i],
        ["Risk premium", r, risk_amount],
        ["Margin", margin_pct, margin_amount],
        ["Bid price before rounding", None, raw],
        ["Rounding", None, idr(bid - raw)],
        ["Bid price (excl. VAT)", None, idr(bid)],
        ["VAT", tax_pct, vat],
        ["Bid price incl. VAT", None, idr(bid + vat)],
    ]
    diff_rows = [[x["factor"], x["weight"], x["score"], x["note"]] for x in diff["lines"]]
    record["result"] = result(
        summary=[("Difficulty index", diff["index"], ""), ("Risk premium", risk_pct, "%"), ("Margin", margin_pct, "%"),
                 ("Cost ratio ABP/revenue", ratio, "%")],
        values=[("Total project cost budget (ABP)", abp_i, "Rp"), ("Risk premium amount", risk_amount, "Rp"),
                ("Margin amount", margin_amount, "Rp"), ("Bid price (excl. VAT)", idr(bid), "Rp"),
                ("Bid price incl. VAT", idr(bid + vat), "Rp"), ("Minimum client price", idr(min_price), "Rp"),
                ("Price-list value of the work items", idr(list_value) if list_value else None, "Rp"),
                ("Difficulty score (weighted average)", diff["score"], ""),
                ("Duration (weeks)", num(record.get("duration_weeks")), "")],
        tables=[
            table("Price build-up", ["Item", "Rate (%)", "Amount (IDR)"], build),
            table("Cost budget by group", ["Cost group", "Amount (IDR)", "Share (%)"], group_rows),
            table("Cost budget lines", ["Cost group", "Description", "Quantity", "Days", "Unit", "Unit cost (IDR)", "Amount (IDR)"],
                  line_rows, key=["Description", "Amount (IDR)"]),
            table("Difficulty factors", ["Factor", "Weight", "Score", "Note"], diff_rows, key=["Factor", "Score"]),
        ],
        notes=[
            "ABP = Σ quantity × days × unit cost; lines from the price list take the unit cost (HPJ) of the rate build-up.",
            "Risk premium and margin are percentages of the ABP; bid price = ABP + risk premium + margin, rounded up.",
            "Minimum client price = lines from the price list at their minimum selling price, other lines at cost.",
            "Difficulty index = weighted average of the factor scores, rounded half up; the region zone scores itself.",
        ],
        method="Pricing & Budgeting Decision (blueprint A.1.1, A.1.3, A.1.4)",
    )


def quotation_from_pbd(pbd: Rec, rates: Dict[str, Rec], client: Optional[Rec], today: str) -> Rec:
    """Conversion to client rates (A.1.5): quotation data from a PBD.

    Each price-list line becomes an item at its unit cost × (1 + risk + margin), rounded up to
    1,000 and never below the rate's minimum selling price. With "spread" the project costs
    that are not work items (labour, accommodation, pre-project …) are spread over the work
    items in proportion to their cost; mobilisation and demobilisation stay separate items.
    With "separate" every budget line is its own item."""
    k = 1 + (num(pbd.get("risk_premium_pct")) or 0) / 100 + (num(pbd.get("margin_pct")) or 0) / 100
    rows = [r for r in pbd.get("costs") or [] if _units(r) > 0]
    if not rows:
        raise CommercialError("The PBD has no cost lines to convert")
    if any(num(r.get("unit_cost")) is None for r in rows):
        raise CommercialError("Every cost line needs a unit cost before the conversion")

    def is_work(r: Rec) -> bool:
        return bool(rates.get(str(r.get("rate_id") or ""))) and str(r.get("section")) not in MOB_SECTIONS

    work = [r for r in rows if is_work(r)]
    mob = [r for r in rows if str(r.get("section")) in MOB_SECTIONS]
    other = [r for r in rows if r not in work and r not in mob]
    work_cost = sum(_units(r) * float(r["unit_cost"]) for r in work)
    spread = pbd.get("conversion", "spread") != "separate" and work_cost > 0
    loading = 1 + (sum(_units(r) * float(r["unit_cost"]) for r in other) / work_cost if spread else 0.0)

    def item(r: Rec, factor: float) -> Rec:
        rate = rates.get(str(r.get("rate_id") or ""))
        price = round_up(float(r["unit_cost"]) * factor * k, 1000)
        if rate and num(rate.get("min_price")):
            price = max(price, float(rate["min_price"]))
        return {"rate_id": rate["id"] if rate else "", "description": r.get("description") or (rate or {}).get("description") or "",
                "unit": r.get("unit") or (rate or {}).get("unit") or "ls", "qty": round(_units(r), 6), "unit_price": price}

    items = [item(r, loading) for r in work] if spread else [item(r, 1.0) for r in work + other]
    items += [item(r, 1.0) for r in mob]
    valid = (parse_date(today) or date.today()) + timedelta(days=30)
    return {
        "project_id": pbd.get("project_id"), "pbd_id": pbd.get("id"), "date": today, "valid_until": valid.isoformat(),
        "status": "draft", "price_tier": (client or {}).get("pricing_tier") or "client", "items": items,
        "discount_pct": 0, "tax_pct": num(pbd.get("tax_pct")) if num(pbd.get("tax_pct")) is not None else 11,
        "mob_demob": "included" if mob else "excluded",
        "notes": "",
    }


# --------------------------------------------------------------------------- #
# A.1.2 Client decision
# --------------------------------------------------------------------------- #

def client_decision_compute(record: Rec, pbd: Optional[Rec], project: Optional[Rec], settings: Optional[Rec]) -> None:
    checks: List[Rec] = []
    if pbd:
        for key, src in (("proposed_price", "bid_price"), ("price_min", "min_client_price"), ("difficulty_index", "difficulty_index"),
                         ("risk_premium_pct", "risk_premium_pct"), ("zone", "zone")):
            record[key] = pbd.get(src)
        if not record.get("location") and pbd.get("location"):
            record["location"] = pbd["location"]
        if not record.get("procurement") and pbd.get("procurement"):
            record["procurement"] = pbd["procurement"]
        if pbd.get("wf_status") != "approved":
            checks.append(check("warn", "The PBD is not approved yet."))
    else:
        for key in ("proposed_price", "price_min", "difficulty_index", "risk_premium_pct", "zone"):
            record[key] = None
        checks.append(check("info", "Link the PBD to take over the proposed price, the minimum price and the difficulty index."))
    if project:
        record["client_id"] = project.get("client_id") or ""
    decided = num(record.get("decided_price"))
    floor = num(record.get("price_min"))
    if decided is not None and floor and decided < floor - 0.5:
        raise CommercialError("The decided offer price is below the minimum client price")
    ceiling = num(record.get("price_max"))
    if decided is not None and ceiling and decided > ceiling + 0.5:
        checks.append(check("warn", "The decided offer price is above the highest price (owner's estimate)."))
    if decided is None:
        checks.append(check("info", "Enter the decided offer price."))
    start, end = parse_date(record.get("start_date")), parse_date(record.get("end_date"))
    if start and end and end < start:
        raise CommercialError("The end date is before the start date")
    price = decided if decided is not None else num(record.get("proposed_price"))
    terms = record.get("payment_terms") or []
    total = sum(num(t.get("percent")) or 0 for t in terms)
    if terms and abs(total - 100) > 0.01:
        checks.append(check("warn", "The payment terms add up to {total}%, not 100%.", total=round(total, 2)))
    record["approval_level"] = approval_level(price, settings)
    record["checks"] = checks
    rows = [[t.get("name") or "", num(t.get("percent")), idr((price or 0) * (num(t.get("percent")) or 0) / 100), t.get("condition") or ""]
            for t in terms]
    record["result"] = result(
        values=[("Decided offer price", decided, "Rp"), ("Proposed price (PBD)", num(record.get("proposed_price")), "Rp"),
                ("Minimum client price", floor, "Rp"), ("Highest price (owner's estimate)", ceiling, "Rp")],
        tables=[table("Payment terms", ["Term", "Share (%)", "Amount (IDR)", "Due when"], rows, key=["Term", "Amount (IDR)"])] if rows else [],
        method="Client decision (blueprint A.1.2)",
    )


# --------------------------------------------------------------------------- #
# A.1.6 Weekly work plan and budget drawdown
# --------------------------------------------------------------------------- #

def work_plan_compute(record: Rec, pbd: Optional[Rec], settings: Optional[Rec]) -> None:
    cfg = config(settings)
    acts = [a for a in record.get("activities") or [] if num(a.get("start_week")) is not None]
    for a in acts:
        end = num(a.get("end_week"))
        if end is not None and end < float(a["start_week"]):
            raise CommercialError("An activity ends before it starts; check the start and end weeks")
    rows = sorted([w for w in record.get("weeks") or [] if num(w.get("week")) is not None], key=lambda w: float(w["week"]))
    weeks_seen = [int(w["week"]) for w in rows]
    if len(weeks_seen) != len(set(weeks_seen)):
        raise CommercialError("Each week may appear only once in the weekly rows")
    n = max([int(num(a.get("end_week")) or a["start_week"]) for a in acts] + weeks_seen + [0])
    by_week = {int(w["week"]): w for w in rows}

    planned = [0.0] * (n + 1)
    if any(num(w.get("planned_pct")) is not None for w in rows):
        for k, w in by_week.items():
            planned[k] = num(w.get("planned_pct")) or 0.0
        plan_source = "rows"
    else:
        for a in acts:
            s, e = int(a["start_week"]), int(num(a.get("end_week")) or a["start_week"])
            weight = num(a.get("weight_pct")) or 0.0
            for k in range(s, e + 1):
                planned[k] += weight / (e - s + 1)
        plan_source = "gantt"
    actual = [num(by_week.get(k, {}).get("actual_pct")) for k in range(n + 1)]
    reported = [k for k in range(1, n + 1) if actual[k] is not None or num(by_week.get(k, {}).get("realised")) is not None]
    last = max(reported) if reported else 0

    def col(name: str) -> List[float]:
        return [num(by_week.get(k, {}).get(name)) or 0.0 for k in range(n + 1)]

    budget, drawdown, realised = col("budget_plan"), col("drawdown"), col("realised")
    cum = lambda xs, upto: sum(xs[1:upto + 1])  # noqa: E731
    total_plan, total_draw, total_real = idr(cum(budget, n)), idr(cum(drawdown, n)), idr(cum(realised, n))
    planned_to_date = round(cum(planned, last), 2) if last else 0.0
    actual_to_date = round(sum(a or 0.0 for a in actual[1:last + 1]), 2) if last else 0.0
    budget_to_date = idr(cum(budget, last))

    pbd_budget = num((pbd or {}).get("abp"))
    pbd_weeks = num((pbd or {}).get("duration_weeks"))
    revenue = num((pbd or {}).get("bid_price"))
    projected = max(total_plan, total_real)
    ratio = pct(projected, revenue) if revenue else None
    checks: List[Rec] = []
    weights = sum(num(a.get("weight_pct")) or 0 for a in acts)
    if acts and abs(weights - 100) > 0.01:
        checks.append(check("warn", "The activity weights add up to {total}%, not 100%.", total=round(weights, 2)))
    if pbd is None:
        checks.append(check("info", "Link the PBD to check the budget and the duration against it."))
    else:
        if pbd_budget and abs(total_plan - pbd_budget) > max(0.01 * pbd_budget, 1):
            checks.append(check("warn", "The weekly budget plan totals {plan_idr}; the PBD budget is {pbd_idr} ({diff}% difference).",
                                plan_idr=total_plan, pbd_idr=pbd_budget, diff=round((total_plan - pbd_budget) / pbd_budget * 100, 1)))
        if pbd_weeks and n > pbd_weeks:
            checks.append(check("warn", "The plan runs {weeks} weeks, longer than the {pbd_weeks} weeks in the PBD.",
                                weeks=n, pbd_weeks=int(pbd_weeks)))
        if pbd.get("wf_status") != "approved":
            checks.append(check("warn", "The PBD is not approved yet."))
    if last and total_real and cum(realised, last) > budget_to_date + 0.5:
        checks.append(check("warn", "Realised cost to date is above the budget plan to date."))
    if last and actual_to_date < planned_to_date - 5:
        checks.append(check("warn", "Progress is {dev} percentage points behind plan.", dev=round(planned_to_date - actual_to_date, 1)))
    if ratio is not None and ratio > cfg["max_cost_ratio_pct"]:
        checks.append(check("warn", "The projected cost ratio ABP/revenue of {ratio}% is above the company maximum of {max}%.",
                            ratio=ratio, max=cfg["max_cost_ratio_pct"]))

    record.update({
        "duration_weeks": n or None, "pbd_budget": pbd_budget, "pbd_weeks": pbd_weeks, "revenue": revenue,
        "total_plan": float(total_plan), "total_drawdown": float(total_draw), "total_realised": float(total_real),
        "report_week": last or None, "planned_to_date": planned_to_date, "actual_to_date": actual_to_date,
        "deviation": round(actual_to_date - planned_to_date, 2) if last else None, "cost_ratio_pct": ratio, "checks": checks,
    })

    start = parse_date(record.get("start_date"))
    table_rows = []
    cp = ca = cb = cr = 0.0
    s_plan, s_act, s_budget, s_draw, s_real = [(0.0, 0.0)], [(0.0, 0.0)], [(0.0, 0.0)], [(0.0, 0.0)], [(0.0, 0.0)]
    cd = 0.0
    for k in range(1, n + 1):
        cp += planned[k]
        cb += budget[k]
        cd += drawdown[k]
        s_plan.append((k, cp))
        s_budget.append((k, cb / 1e6))
        s_draw.append((k, cd / 1e6))
        if k <= last:
            ca += actual[k] or 0.0
            cr += realised[k]
            s_act.append((k, ca))
            s_real.append((k, cr / 1e6))
        table_rows.append([k, (start + timedelta(days=7 * (k - 1))).isoformat() if start else "", round(planned[k], 2), round(cp, 2),
                           actual[k], round(ca, 2) if k <= last else None, idr(budget[k]), idr(cb), idr(drawdown[k]),
                           idr(realised[k]) if k <= last else None, idr(cr) if k <= last else None,
                           by_week.get(k, {}).get("notes") or ""])
    gantt = [[a.get("activity") or "", int(a["start_week"]), int(num(a.get("end_week")) or a["start_week"]), num(a.get("weight_pct")),
              num(a.get("progress_pct"))] for a in acts]
    record["result"] = result(
        summary=[("Planned progress to date", planned_to_date if last else None, "%"),
                 ("Actual progress to date", actual_to_date if last else None, "%"),
                 ("Reported up to week", last or None, ""), ("Cost ratio ABP/revenue", ratio, "%")],
        values=[("Budget plan", total_plan, "Rp"), ("PBD budget (ABP)", idr(pbd_budget) if pbd_budget else None, "Rp"),
                ("Budget plan to date", budget_to_date if last else None, "Rp"), ("Drawdown requested", total_draw, "Rp"),
                ("Realised cost", total_real, "Rp"), ("Remaining budget", total_plan - total_real, "Rp"),
                ("Duration (weeks)", n or None, ""), ("PBD duration (weeks)", pbd_weeks, "")],
        tables=[
            table("Weekly plan and realisation",
                  ["Week", "Week starts", "Planned (%)", "Planned, cumulative (%)", "Actual (%)", "Actual, cumulative (%)",
                   "Budget plan (IDR)", "Budget, cumulative (IDR)", "Drawdown requested (IDR)", "Realised cost (IDR)",
                   "Realised, cumulative (IDR)", "Notes"], table_rows,
                  key=["Week", "Planned, cumulative (%)", "Actual, cumulative (%)", "Realised cost (IDR)"], note="Notes"),
            table("Activities (Gantt)", ["Activity", "Start week", "End week", "Weight (%)", "Done (%)"], gantt),
        ],
        charts=[c for c in [
            chart("S-curve: planned and actual progress", axis("Week"), axis("Cumulative progress (%)"),
                  series("Planned", s_plan, "line"), series("Actual", s_act if last else [], "both")),
            chart("Budget and realisation", axis("Week"), axis("Cumulative cost (IDR million)"),
                  series("Budget plan", s_budget, "line"), series("Drawdown requested", s_draw if total_draw else [], "line", dash=True),
                  series("Realised cost", s_real if last else [], "both")),
        ] if n],
        notes=["Planned progress per week is taken from the weekly rows; when none is entered it is spread evenly over the weeks of each activity in the Gantt chart."
               if plan_source == "gantt" else "Planned progress per week as entered in the weekly rows."],
        method="Weekly work plan and budget drawdown (blueprint A.1.6)",
    )


def weeks_from_gantt(activities: List[Rec], budget: Optional[float]) -> List[Rec]:
    """Weekly rows with the planned progress from the Gantt chart and the budget spread in the
    same proportion (a starting point the site manager adjusts)."""
    acts = [a for a in activities or [] if num(a.get("start_week")) is not None]
    for a in acts:
        if (num(a.get("end_week")) or float(a["start_week"])) < float(a["start_week"]):
            raise CommercialError("An activity ends before it starts; check the start and end weeks")
    last = max([int(num(a.get("end_week")) or a["start_week"]) for a in acts] + [0])
    weekly = [0.0] * last
    for a in acts:
        s, e = int(a["start_week"]), int(num(a.get("end_week")) or a["start_week"])
        for k in range(s, e + 1):
            weekly[k - 1] += (num(a.get("weight_pct")) or 0.0) / (e - s + 1)
    total = sum(weekly) or 1.0
    shares = [round(p, 2) for p in weekly]
    money_ = [float(idr(budget * p / total)) for p in weekly] if budget else []
    if shares:
        # Rounding differences go into the last week so the rows add up exactly.
        shares[-1] = round(sum(weekly) - sum(shares[:-1]), 2)
        if budget:
            money_[-1] = float(idr(budget - sum(money_[:-1])))
    return [{"week": k, "planned_pct": shares[k - 1], "budget_plan": money_[k - 1] if budget else None} for k in range(1, len(shares) + 1)]


# --------------------------------------------------------------------------- #
# A.1.9 Bank guarantees and SKBDN
# --------------------------------------------------------------------------- #

def guarantee_compute(record: Rec, contract: Optional[Rec], client: Optional[Rec], settings: Optional[Rec],
                      today: Optional[str] = None) -> None:
    cfg = config(settings)
    if not record.get("direction"):
        # The company asks clients for an SKBDN as payment security; bank guarantees are issued for the client.
        record["direction"] = "received" if record.get("type") == "skbdn" else "issued"
    if not record.get("beneficiary"):
        if record["direction"] == "issued" and client:
            record["beneficiary"] = client.get("name") or ""
        elif record["direction"] == "received" and settings:
            record["beneficiary"] = settings.get("company_name") or ""
    value = num((contract or {}).get("value"))
    required = num(record.get("required_pct"))
    if num(record.get("amount")) is None and required is not None and value:
        record["amount"] = float(idr(value * required / 100))
    amount = num(record.get("amount"))
    record["pct_of_contract"] = pct(amount, value) if amount is not None and value else None
    record["fee_amount"] = float(idr(amount * (num(record.get("fee_pct")) or 0) / 100)) if amount and num(record.get("fee_pct")) else None
    record["collateral_amount"] = (float(idr(amount * (num(record.get("collateral_pct")) or 0) / 100))
                                   if amount and num(record.get("collateral_pct")) else None)
    issue, expiry = parse_date(record.get("issue_date")), parse_date(record.get("expiry_date"))
    if issue and expiry and expiry < issue:
        raise CommercialError("The expiry date is before the issue date")
    record["expiry_status"] = expiry_status(record, cfg["guarantee_warning_days"], today)
    checks: List[Rec] = []
    end = parse_date((contract or {}).get("end_date"))
    if expiry and end and expiry < end and record.get("type") in ("performance", "advance", "maintenance"):
        checks.append(check("warn", "The guarantee expires before the contract work ends."))
    if required is not None and amount is not None and value and abs(amount - value * required / 100) > 1:
        checks.append(check("info", "The amount differs from the required {pct}% of the contract value.", pct=required))
    if record["expiry_status"] == "expiring":
        checks.append(check("warn", "The guarantee expires within {days} days.", days=cfg["guarantee_warning_days"]))
    elif record["expiry_status"] == "expired":
        checks.append(check("error", "The guarantee has expired."))
    record["checks"] = checks


def expiry_status(record: Rec, warning_days: int, today: Optional[str] = None) -> str:
    if record.get("status") in ("released", "claimed", "cancelled"):
        return ""
    expiry = parse_date(record.get("expiry_date"))
    if not expiry:
        return ""
    days = (expiry - (parse_date(today) or date.today())).days
    return "expired" if days < 0 else "expiring" if days <= warning_days else "ok"


# --------------------------------------------------------------------------- #
# A.1.10–A.1.12 Receivables, aging, NPAR, client card
# --------------------------------------------------------------------------- #

AGING_BUCKETS: List[Tuple[str, str]] = [
    ("current", "Not yet due"), ("d1_30", "1–30 days overdue"), ("d31_60", "31–60 days overdue"),
    ("d61_90", "61–90 days overdue"), ("over_90", "More than 90 days overdue"),
]
# The blueprint's matrix: age since the invoice date.
AGE_BUCKETS: List[Tuple[str, str]] = [
    ("lt30", "Less than 30 days"), ("d30_90", "30–90 days"), ("d91_180", "91–180 days"), ("d181_360", "181–360 days"),
    ("over_360", "More than 360 days"),
]
VALUE_KINDS = ("contract", "spk", "", None)  # contract kinds that carry the client's contract value
VALUE_STATUSES = ("signed", "amended", "closed")
CONTRACTED = ("contract", "ongoing", "reporting", "completed")  # project stages with a contract


def _overdue_bucket(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    return "d1_30" if days_past_due <= 30 else "d31_60" if days_past_due <= 60 else "d61_90" if days_past_due <= 90 else "over_90"


def _age_bucket(days: int) -> str:
    return "lt30" if days < 30 else "d30_90" if days <= 90 else "d91_180" if days <= 180 else "d181_360" if days <= 360 else "over_360"


def is_issued(inv: Rec) -> bool:
    return inv.get("status") == "sent"


def _paid_on(inv: Rec) -> Optional[date]:
    dates = [parse_date(p.get("date")) for p in inv.get("payments") or []]
    known = [d for d in dates if d]
    return max(known) if known else None


def invoice_row(inv: Rec, today: date, cfg: Rec, project: Optional[Rec], client: Optional[Rec]) -> Rec:
    issued = parse_date(inv.get("date")) or today
    due = parse_date(inv.get("due_date")) or issued + timedelta(days=cfg["payment_days"])
    since = (today - issued).days
    past_due = (today - due).days
    notes = inv.get("collection_notes") or []
    return {
        "id": inv.get("id"), "number": inv.get("number"), "project_id": inv.get("project_id"),
        "project": (project or {}).get("name") or "", "client_id": (project or {}).get("client_id") or "",
        "client": (client or {}).get("name") or "", "date": inv.get("date"), "due_date": due.isoformat(),
        "term": inv.get("term") or "", "total": num(inv.get("total")) or 0.0, "paid": num(inv.get("paid")) or 0.0,
        "outstanding": num(inv.get("outstanding")) or 0.0, "days_since_invoice": since, "days_past_due": max(0, past_due),
        "bucket": _overdue_bucket(past_due), "age_bucket": _age_bucket(since),
        "owner": "npar" if since > cfg["npar_days"] else "commercial", "last_note": notes[-1] if notes else None,
        "notes_count": len(notes),
    }


def receivables(invoices: List[Rec], projects: List[Rec], clients: List[Rec], settings: Optional[Rec],
                today: Optional[str] = None, client_id: Optional[str] = None) -> Rec:
    cfg = config(settings)
    as_of = parse_date(today) or date.today()
    proj = {p["id"]: p for p in projects}
    cli = {c["id"]: c for c in clients}
    issued = [i for i in invoices if is_issued(i)]
    if client_id:
        issued = [i for i in issued if proj.get(i.get("project_id") or "", {}).get("client_id") == client_id]
    rows = []
    for inv in issued:
        p = proj.get(inv.get("project_id") or "")
        rows.append(invoice_row(inv, as_of, cfg, p, cli.get((p or {}).get("client_id") or "")))
    open_rows = [r for r in rows if r["outstanding"] > 0]
    buckets: Dict[str, Rec] = {k: {"key": k, "label": label, "amount": 0.0, "count": 0} for k, label in AGING_BUCKETS}
    ages: Dict[str, Rec] = {k: {"key": k, "label": label, "amount": 0.0, "count": 0} for k, label in AGE_BUCKETS}
    per_client: Dict[str, Rec] = {}
    for r in open_rows:
        for target, key in ((buckets, r["bucket"]), (ages, r["age_bucket"])):
            target[key]["amount"] += r["outstanding"]
            target[key]["count"] += 1
        c = per_client.setdefault(r["client_id"], {"client_id": r["client_id"], "client": r["client"], "outstanding": 0.0, "npar": 0.0,
                                                   **{k: 0.0 for k, _ in AGING_BUCKETS}})
        c["outstanding"] += r["outstanding"]
        c[r["bucket"]] += r["outstanding"]
        if r["owner"] == "npar":
            c["npar"] += r["outstanding"]
    open_rows.sort(key=lambda r: -r["days_since_invoice"])
    npar = [r for r in open_rows if r["owner"] == "npar"]
    return {
        "as_of": as_of.isoformat(), "npar_days": cfg["npar_days"],
        "totals": {"invoiced": sum(r["total"] for r in rows), "paid": sum(r["paid"] for r in rows),
                   "outstanding": sum(r["outstanding"] for r in open_rows),
                   "overdue": sum(r["outstanding"] for r in open_rows if r["bucket"] != "current"),
                   "npar": sum(r["outstanding"] for r in npar), "open_invoices": len(open_rows)},
        "buckets": list(buckets.values()), "age_buckets": list(ages.values()),
        "by_client": sorted(per_client.values(), key=lambda c: -c["outstanding"]),
        "invoices": open_rows, "npar": npar,
    }


def payment_behaviour(invoices: List[Rec], today: date, cfg: Rec) -> Rec:
    """Average days to pay (fully paid invoices) and the share paid on time among the invoices that
    have fallen due (paid, or still open past their due date)."""
    days: List[int] = []
    due_count = on_time = late_open = 0
    for inv in invoices:
        issued = parse_date(inv.get("date"))
        if not issued:
            continue
        due = parse_date(inv.get("due_date")) or issued + timedelta(days=cfg["payment_days"])
        paid_on = _paid_on(inv)
        if inv.get("payment_status") == "paid" and paid_on:
            days.append((paid_on - issued).days)
            due_count += 1
            on_time += 1 if paid_on <= due else 0
        elif (num(inv.get("outstanding")) or 0) > 0 and today > due:
            due_count += 1
            late_open += 1
    return {"avg_days_to_pay": round(sum(days) / len(days), 1) if days else None, "paid_invoices": len(days),
            "on_time_rate_pct": pct(on_time, due_count, 1) if due_count else None, "invoices_due": due_count,
            "late_open": late_open}


def contract_values(projects: List[Rec], contracts: List[Rec]) -> Dict[str, float]:
    """Contract value per project: signed client contracts (not SPMK or subcontracts), else the
    value written on the project."""
    out: Dict[str, float] = {}
    for c in contracts:
        if c.get("kind") in VALUE_KINDS and c.get("status") in VALUE_STATUSES:
            out[c.get("project_id") or ""] = out.get(c.get("project_id") or "", 0.0) + (num(c.get("value")) or 0.0)
    for p in projects:
        if p["id"] not in out and num(p.get("contract_value")) and p.get("status") in CONTRACTED:
            out[p["id"]] = float(p["contract_value"])
    return out


def client_card(client: Rec, projects: List[Rec], contracts: List[Rec], invoices: List[Rec], plans: List[Rec],
                pbds: List[Rec], quotes: List[Rec], decisions: List[Rec], clients: List[Rec], settings: Optional[Rec],
                today: Optional[str] = None) -> Rec:
    cfg = config(settings)
    as_of = parse_date(today) or date.today()
    mine = [p for p in projects if p.get("client_id") == client["id"]]
    ids = {p["id"] for p in mine}
    values = contract_values(mine, [c for c in contracts if c.get("project_id") in ids])
    invs = [i for i in invoices if i.get("project_id") in ids and is_issued(i)]
    ar = receivables(invs, mine, clients, settings, as_of.isoformat())
    behaviour = payment_behaviour(invs, as_of, cfg)
    progress = latest_progress(plans)
    by_status: Dict[str, int] = {}
    services: Dict[str, int] = {}
    provinces: Dict[str, int] = {}
    rows = []
    for p in sorted(mine, key=lambda p: str(p.get("start_date") or ""), reverse=True):
        by_status[p.get("status") or ""] = by_status.get(p.get("status") or "", 0) + 1
        for s in p.get("services") or []:
            services[s] = services.get(s, 0) + 1
        if p.get("province"):
            provinces[p["province"]] = provinces.get(p["province"], 0) + 1
        pi = [i for i in invs if i.get("project_id") == p["id"]]
        rows.append({"id": p["id"], "code": p.get("code"), "name": p.get("name"), "status": p.get("status"),
                     "province": p.get("province") or "", "services": p.get("services") or [], "start_date": p.get("start_date"),
                     "contract_value": values.get(p["id"]), "invoiced": sum(num(i.get("total")) or 0 for i in pi),
                     "paid": sum(num(i.get("paid")) or 0 for i in pi), "outstanding": sum(num(i.get("outstanding")) or 0 for i in pi),
                     "progress_pct": progress.get(p["id"])})
    years = [int(str(p.get("start_date"))[:4]) for p in mine if str(p.get("start_date") or "")[:4].isdigit()]
    since = num(client.get("since_year")) or (min(years) if years else None)
    npar_amount = ar["totals"]["npar"]
    rate = behaviour["on_time_rate_pct"]
    if npar_amount > 0 or (rate is not None and rate < 50):
        rating = "poor"
    elif (rate is not None and rate < 80) or ar["totals"]["overdue"] > 0:
        rating = "watch"
    elif rate is None:
        rating = "new"
    else:
        rating = "good"

    def brief(r: Rec, fields: Sequence[str]) -> Rec:
        return {k: r.get(k) for k in ("id",) + tuple(fields)}

    return {
        "as_of": as_of.isoformat(),
        "client": {k: client.get(k) for k in ("id", "name", "type", "pricing_tier", "contact_person", "contact_title", "phone",
                                              "email", "npwp", "address")} | {"since_year": int(since) if since else None},
        "stats": {"projects": len(mine), "projects_by_status": by_status, "contract_value": sum(values.values()),
                  "invoiced": ar["totals"]["invoiced"], "paid": ar["totals"]["paid"], "outstanding": ar["totals"]["outstanding"],
                  "overdue": ar["totals"]["overdue"], "npar": npar_amount, **behaviour, "rating": rating},
        "services": services, "provinces": provinces, "projects": rows,
        "aging": ar["buckets"], "age_buckets": ar["age_buckets"], "invoices": ar["invoices"], "npar": ar["npar"],
        "pipeline": {
            "pbd": [brief(r, ("number", "project_id", "date", "bid_price", "wf_status")) for r in pbds if r.get("project_id") in ids],
            "quotes": [brief(r, ("number", "project_id", "date", "status", "total")) for r in quotes if r.get("project_id") in ids],
            "client_decisions": [brief(r, ("number", "project_id", "date", "decided_price", "proposed_price", "wf_status"))
                                 for r in decisions if r.get("project_id") in ids],
        },
    }


def latest_progress(plans: List[Rec]) -> Dict[str, float]:
    """Actual progress to date of the latest weekly plan of each project."""
    out: Dict[str, Tuple[str, float]] = {}
    for w in plans:
        key = str(w.get("date") or "") + str(w.get("updated_at") or "")
        if w.get("actual_to_date") is not None and (w.get("project_id") not in out or key > out[w["project_id"]][0]):
            out[w["project_id"]] = (key, float(w["actual_to_date"]))
    return {k: v[1] for k, v in out.items()}


# --------------------------------------------------------------------------- #
# A.1.14 Commercial overview for the management dashboard
# --------------------------------------------------------------------------- #

def _by(records: Iterable[Rec], key: str, value: str) -> Dict[str, Rec]:
    out: Dict[str, Rec] = {}
    for r in records:
        k = str(r.get(key) or "draft")
        slot = out.setdefault(k, {"count": 0, "value": 0.0})
        slot["count"] += 1
        slot["value"] += num(r.get(value)) or 0.0
    return out


def overview(data: Dict[str, List[Rec]], settings: Optional[Rec], service_labels: Dict[str, str], today: Optional[str] = None) -> Rec:
    cfg = config(settings)
    as_of = parse_date(today) or date.today()
    projects, clients, contracts = data["projects"], data["clients"], data["contracts"]
    pbds = {p["id"]: p for p in data["pbd"]}
    proj = {p["id"]: p for p in projects}
    ar = receivables(data["invoices"], projects, clients, settings, as_of.isoformat())
    values = contract_values(projects, contracts)

    plans = []
    for w in data["work_plans"]:
        fresh = copy.deepcopy(w)
        try:
            work_plan_compute(fresh, pbds.get(w.get("pbd_id") or ""), settings)
        except CommercialError:
            continue
        plans.append({"id": w["id"], "number": w.get("number"), "project_id": w.get("project_id"),
                      "project": proj.get(w.get("project_id") or "", {}).get("name") or "", "wf_status": w.get("wf_status"),
                      "pbd_budget": fresh.get("pbd_budget"), "plan_budget": fresh.get("total_plan"), "drawdown": fresh.get("total_drawdown"),
                      "realised": fresh.get("total_realised"), "report_week": fresh.get("report_week"),
                      "duration_weeks": fresh.get("duration_weeks"), "planned_pct": fresh.get("planned_to_date"),
                      "actual_pct": fresh.get("actual_to_date"), "deviation_pct": fresh.get("deviation"),
                      "cost_ratio_pct": fresh.get("cost_ratio_pct")})

    def group_stats(key_of: Callable[[Rec], List[str]]) -> List[Rec]:
        clients_of: Dict[str, set] = {}
        count: Dict[str, int] = {}
        value: Dict[str, float] = {}
        for p in projects:
            if p.get("status") == "cancelled":
                continue
            for key in key_of(p) or [""]:
                clients_of.setdefault(key, set()).add(p.get("client_id"))
                count[key] = count.get(key, 0) + 1
                value[key] = value.get(key, 0.0) + values.get(p["id"], 0.0)
        return [{"key": k, "clients": len(clients_of[k]), "projects": count[k], "contract_value": value[k]}
                for k in sorted(count, key=lambda k: -value[k])]

    by_service = group_stats(lambda p: p.get("services") or [])
    for row in by_service:
        row["label"] = service_labels.get(row["key"], "Not set" if not row["key"] else row["key"])
    by_province = group_stats(lambda p: [p.get("province") or ""])
    for row in by_province:
        row["label"] = PROVINCE_NAME.get(row["key"], "Not set")
        row["zone"] = PROVINCE_ZONE.get(row["key"], "")

    active_g = []
    expiring = []
    for g in data["guarantees"]:
        if g.get("status") not in ("issued",):
            continue
        status = expiry_status(g, cfg["guarantee_warning_days"], as_of.isoformat())
        active_g.append(g)
        if status in ("expiring", "expired"):
            exp = parse_date(g.get("expiry_date"))
            expiring.append({"id": g["id"], "number": g.get("number"), "type": g.get("type"), "direction": g.get("direction"),
                             "project_id": g.get("project_id"), "expiry_date": g.get("expiry_date"),
                             "days": (exp - as_of).days if exp else None, "amount": num(g.get("amount")), "status": status})
    expiring.sort(key=lambda x: x["days"] if x["days"] is not None else 0)
    ratios = [float(p["cost_ratio_pct"]) for p in pbds.values() if p.get("wf_status") == "approved" and num(p.get("cost_ratio_pct")) is not None]
    signed = [c for c in contracts if c.get("status") in VALUE_STATUSES]
    by_kind: Dict[str, Rec] = {}
    for c in signed:
        slot = by_kind.setdefault(c.get("kind") or "contract", {"count": 0, "value": 0.0})
        slot["count"] += 1
        slot["value"] += num(c.get("value")) or 0.0
    return {
        "as_of": as_of.isoformat(),
        "pipeline": {
            "pbd": _by(pbds.values(), "wf_status", "bid_price"),
            "client_decisions": _by(data["client_decisions"], "wf_status", "decided_price"),
            "quotes": _by(data["quotes"], "status", "total"),
            "projects": {k: v["count"] for k, v in _by(projects, "status", "contract_value").items()},
        },
        "contracts": {"count": sum(1 for c in signed if c.get("kind") in VALUE_KINDS),
                      "value": sum(num(c.get("value")) or 0.0 for c in signed if c.get("kind") in VALUE_KINDS), "by_kind": by_kind},
        "receivables": ar["totals"], "aging": ar["buckets"], "age_buckets": ar["age_buckets"], "npar": ar["npar"],
        "by_client": ar["by_client"][:10],
        "projects_budget": plans,
        "clients_by_service": by_service, "clients_by_province": by_province,
        "guarantees": {"active": len(active_g), "amount": sum(num(g.get("amount")) or 0.0 for g in active_g), "expiring": expiring},
        "cost_ratio": {"average_pct": round(sum(ratios) / len(ratios), 2) if ratios else None, "max_pct": cfg["max_cost_ratio_pct"],
                       "approved_pbd": len(ratios)},
    }
