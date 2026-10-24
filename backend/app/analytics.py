from __future__ import annotations

from collections import Counter, OrderedDict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import math
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .ollama_client import AIUnavailableError, ask_strict


logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC "now" (dates in the CSV are naive), without the deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_float(val: Any) -> Optional[float]:
    try:
        if val in (None, "", "None"):
            return None
        number = float(val)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_date(val: Any) -> Optional[datetime]:
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    start_dt = parse_date(row.get("StartDate"))
    end_dt = parse_date(row.get("EndDate"))
    if not end_dt and start_dt:
        end_dt = start_dt

    final_depth = parse_float(row.get("FinalDepth_m"))
    target_depth = parse_float(row.get("TargetDepth_m"))
    gw_depth = parse_float(row.get("GroundwaterDepth_m"))
    avg_spt = parse_float(row.get("Avg_SPT_N60"))

    return {
        "borehole_id": row.get("BoreholeID") or "",
        "project": row.get("ProjectName") or "",
        "site": row.get("SiteName") or "",
        "latitude": parse_float(row.get("Latitude")),
        "longitude": parse_float(row.get("Longitude")),
        "start_date": row.get("StartDate") or "",
        "end_date": row.get("EndDate") or "",
        "start_dt": start_dt,
        "end_dt": end_dt,
        "duration_days": ((
            (end_dt - start_dt).days + 1
        ) if start_dt and end_dt else None),
        "method": row.get("DrillingMethod") or "",
        "target_depth": target_depth,
        "final_depth": final_depth,
        "groundwater_depth": gw_depth,
        "groundwater_flag": str(row.get("GroundwaterEncountered")).lower() in ("true", "yes", "1"),
        "soil_description": row.get("SoilDescription") or "",
        "uscs": row.get("USCS_Class") or "",
        "avg_spt": avg_spt,
        "contractor": row.get("Contractor") or "",
        "geologist": row.get("LoggingGeologist") or "",
        "remarks": row.get("Remarks") or "",
    }


def filter_period(
    rows: List[Dict[str, Any]],
    period: str,
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for r in rows:
        dt = r.get("start_dt")
        if not dt:
            continue
        if period == "weekly":
            if start_date and end_date:
                if start_date <= dt <= end_date:
                    filtered.append(r)
            else:
                cutoff = _utcnow() - timedelta(days=7)
                if dt >= cutoff:
                    filtered.append(r)
        else:
            if month and year:
                if dt.year == year and dt.month == month:
                    filtered.append(r)
            else:
                cutoff = _utcnow() - timedelta(days=30)
                if dt >= cutoff:
                    filtered.append(r)
    return filtered


def _avg(values: Iterable[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _period_range(rows: Sequence[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    dates = [r["start_dt"] for r in rows if r.get("start_dt")]
    if not dates:
        return {"from": None, "to": None}
    return {"from": dates[0].strftime("%Y-%m-%d"), "to": dates[-1].strftime("%Y-%m-%d")}


def compute_dashboard(rows_raw: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [normalize_row(r) for r in rows_raw]
    rows = sorted([r for r in rows if r.get("start_dt")], key=lambda r: r["start_dt"])

    total = len(rows)
    avg_depth = _avg(r["final_depth"] for r in rows)
    avg_gw = _avg(r["groundwater_depth"] for r in rows if r.get("groundwater_flag"))
    total_meterage = round(sum((r["final_depth"] or 0) for r in rows), 1)
    methods = Counter(r["method"] for r in rows if r.get("method"))
    uscs_counts = Counter(r["uscs"] for r in rows if r.get("uscs"))
    projects = sorted({r["project"] for r in rows if r.get("project")})
    contractors = Counter(r["contractor"] for r in rows if r.get("contractor"))

    period_range = _period_range(rows)
    period_label = None
    if period_range["from"] and period_range["to"]:
        period_label = f"{period_range['from']} to {period_range['to']}"

    recent = sorted(rows, key=lambda r: r["start_dt"] or datetime.min, reverse=True)[:5]
    recent_payload = [
        {
            "borehole_id": r["borehole_id"],
            "project": r["project"],
            "site": r["site"],
            "start_date": r["start_date"],
            "final_depth_m": r["final_depth"],
            "groundwater_depth_m": r["groundwater_depth"],
            "method": r["method"],
        }
        for r in recent
    ]

    return {
        "total_boreholes": total,
        "avg_final_depth_m": avg_depth,
        "avg_groundwater_depth_m": avg_gw,
        "total_meterage_m": total_meterage,
        "active_projects": len(projects),
        "project_list": projects,
        "method_breakdown": dict(methods),
        "uscs_breakdown": dict(uscs_counts),
        "top_contractor": contractors.most_common(1)[0][0] if contractors else None,
        "period_range": period_range,
        "period_label": period_label,
        "recent_reports": recent_payload,
    }


def build_summary_report(
    rows_raw: List[Dict[str, Any]],
    period: str,
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    rows_all = [normalize_row(r) for r in rows_raw]
    rows_all = sorted([r for r in rows_all if r.get("start_dt")], key=lambda r: r["start_dt"])
    rows = filter_period(rows_all, period, start_date=start_date, end_date=end_date, month=month, year=year)
    now = _utcnow().strftime("%Y-%m-%d %H:%M UTC")

    projects = sorted({r["project"] for r in rows if r.get("project")})
    sites = sorted({r["site"] for r in rows if r.get("site")})
    methods = Counter(r["method"] for r in rows if r.get("method"))
    uscs_counts = Counter(r["uscs"] for r in rows if r.get("uscs"))
    contractors = Counter(r["contractor"] for r in rows if r.get("contractor"))

    avg_depth = _avg(r["final_depth"] for r in rows)
    avg_gw = _avg(r["groundwater_depth"] for r in rows if r.get("groundwater_flag"))
    avg_spt = _avg(r["avg_spt"] for r in rows)
    total_meterage = round(sum((r["final_depth"] or 0) for r in rows), 1)

    actual_range: Dict[str, Optional[str]]
    if period == "weekly" and start_date and end_date:
        # Label the range the user asked for, not just the days that happen to have logs.
        actual_range = {"from": start_date.strftime("%Y-%m-%d"), "to": end_date.strftime("%Y-%m-%d")}
    elif rows:
        actual_range = {"from": rows[0]["start_dt"].strftime("%Y-%m-%d"), "to": rows[-1]["start_dt"].strftime("%Y-%m-%d")}
    else:
        actual_range = {"from": None, "to": None}

    period_label = None
    if period == "weekly" and actual_range["from"] and actual_range["to"]:
        period_label = f"{actual_range['from']} to {actual_range['to']}"
    elif period == "monthly":
        if month and year:
            period_label = datetime(year, month, 1).strftime("%B %Y")
        elif actual_range["to"]:
            period_label = f"Up to {actual_range['to']}"

    stats = {
        "as_of": now,
        "boreholes": len(rows),
        "projects": projects,
        "sites": sites,
        "avg_final_depth_m": avg_depth,
        "avg_groundwater_depth_m": avg_gw,
        "avg_spt_n60": avg_spt,
        "total_meterage_m": total_meterage,
        "method_breakdown": dict(methods),
        "uscs_breakdown": dict(uscs_counts),
        "top_contractor": contractors.most_common(1)[0][0] if contractors else None,
        "period_range": actual_range,
        "period_label": period_label,
    }

    lines = [
        f"Soil boring {period} summary ({period_label or 'latest interval'})",
        f"- Boreholes executed: {stats['boreholes']}",
        f"- Active projects: {', '.join(projects) if projects else '-'}",
        f"- Sites logged: {', '.join(sites) if sites else '-'}",
        f"- Total meterage drilled: {total_meterage} m",
        f"- Average final depth: {avg_depth} m" if avg_depth is not None else "- Average final depth: -",
        f"- Average groundwater depth: {avg_gw} m" if avg_gw is not None else "- Average groundwater depth: -",
        f"- Average SPT N60: {avg_spt}" if avg_spt is not None else "- Average SPT N60: -",
        f"- Dominant methods: {', '.join(f'{k} ({v})' for k, v in methods.most_common(3)) or '-'}",
        f"- Dominant USCS classes: {', '.join(f'{k} ({v})' for k, v in uscs_counts.most_common(3)) or '-'}",
        "",
        "Highlights:",
    ]

    highlights: List[str] = []
    for r in rows[-3:]:
        desc = r["soil_description"][:120] if r["soil_description"] else ""
        depth = f"{r['final_depth']} m" if r["final_depth"] is not None else "-"
        line = f"{r['start_date']} | {r['borehole_id']} at {r['project']} ({r['site']}): depth {depth}"
        if desc:
            line += f" – {desc}"
        lines.append(f"- {line}")
        highlights.append(line)

    narrative = None
    if rows:
        narrative = _ai_exec_summary(
            title=f"Soil boring {period} performance",
            instruction=(
                "You are a geotechnical engineer summarizing soil boring progress. "
                "Using the provided statistics, craft a concise executive summary (<=120 words) "
                "covering drilling volume, groundwater conditions, soil behavior, and any risk signals."
            ),
            # "as_of" changes every minute; leaving it out lets the narrative cache work.
            payload={
                "period": period,
                "stats": {k: v for k, v in stats.items() if k != "as_of"},
                "highlights": highlights,
            },
        )

    return {
        "period": period,
        "text": "\n".join(lines),
        "stats": stats,
        "highlights": highlights,
        "narrative": narrative,
        "period_range": stats["period_range"],
        "period_label": period_label,
    }


def build_summary_text(rows_raw: List[Dict[str, Any]], period: str) -> str:
    return build_summary_report(rows_raw, period).get("text", "")


def build_dashboard_report(rows_raw: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = compute_dashboard(rows_raw)
    narrative = None
    if metrics.get("total_boreholes"):
        narrative = _ai_exec_summary(
            title="Soil boring operations dashboard",
            instruction=(
                "Review the soil boring KPIs and write a short executive briefing (<=90 words). "
                "Highlight borehole volume, depth progression, groundwater observations, and "
                "any notable contractors or methods."
            ),
            payload=metrics,
        )
    report = dict(metrics)
    report["narrative"] = narrative
    return report


_AI_CACHE_TTL_SECONDS = 600
_AI_CACHE_MAX_ENTRIES = 64
_ai_cache: "OrderedDict[str, tuple[float, str]]" = OrderedDict()
_ai_cache_lock = threading.Lock()


def clear_ai_cache() -> None:
    with _ai_cache_lock:
        _ai_cache.clear()


def _ai_exec_summary(title: str, instruction: str, payload: Dict[str, Any]) -> Optional[str]:
    """Generate an AI narrative, cached by content so reloads do not re-run the model.

    Failures are never cached, so the narrative appears as soon as the AI service is back.
    """
    if not payload:
        return None
    try:
        context = json.dumps({"title": title, "data": payload}, indent=2, default=str, sort_keys=True)
    except (TypeError, ValueError):
        context = str(payload)

    key = hashlib.sha256(f"{instruction}\n{context}".encode("utf-8")).hexdigest()
    now = time.time()
    with _ai_cache_lock:
        hit = _ai_cache.get(key)
        if hit and now - hit[0] < _AI_CACHE_TTL_SECONDS:
            _ai_cache.move_to_end(key)
            return hit[1]

    try:
        text = ask_strict(instruction, context=context, timeout=90)
    except AIUnavailableError as exc:
        logger.info("Executive summary skipped: %s", exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Executive summary generation failed: %s", exc)
        return None
    if not text:
        return None

    with _ai_cache_lock:
        _ai_cache[key] = (time.time(), text)
        _ai_cache.move_to_end(key)
        while len(_ai_cache) > _AI_CACHE_MAX_ENTRIES:
            _ai_cache.popitem(last=False)
    return text


_STOPWORDS = frozenset(
    "the and for what which that this with from have has are was were how many much show list give tell "
    "about all any per each into onto over under than then there their them they you your our out not".split()
)
_CONTEXT_COLUMNS = (
    "BoreholeID", "Project", "Site", "StartDate", "Method", "FinalDepth_m", "USCS",
    "GroundwaterDepth_m", "AvgSPT", "Contractor", "SoilDescription", "Remarks",
)


def _fmt_number(value: Optional[float]) -> str:
    return "" if value is None else str(value)


def build_ai_context(question: str, rows_raw: List[Dict[str, Any]], max_rows: int = 30) -> str:
    """Return the most relevant rows as a properly escaped CSV block (no prose)."""
    rows = [normalize_row(r) for r in rows_raw]
    rows = [r for r in rows if r.get("start_dt")]
    rows.sort(key=lambda r: r["start_dt"], reverse=True)
    tokens = {t for t in re.findall(r"\w+", question.lower()) if len(t) >= 3 and t not in _STOPWORDS}

    def score_row(r: Dict[str, Any]) -> int:
        fields = " ".join(
            (r.get(key) or "")
            for key in ("project", "site", "borehole_id", "soil_description", "contractor", "method", "uscs", "geologist")
        ).lower()
        words = set(re.findall(r"\w+", fields))
        return sum(1 for tok in tokens if tok in words)

    ranked = sorted(rows, key=lambda r: (score_row(r), r["start_dt"]), reverse=True)[:max_rows]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CONTEXT_COLUMNS)
    for r in ranked:
        writer.writerow([
            r["borehole_id"],
            r["project"],
            r["site"],
            r["start_date"],
            r["method"],
            _fmt_number(r["final_depth"]),
            r["uscs"],
            _fmt_number(r["groundwater_depth"]),
            _fmt_number(r["avg_spt"]),
            r["contractor"],
            (r["soil_description"] or "")[:200],
            (r["remarks"] or "")[:200],
        ])
    return buffer.getvalue().rstrip("\n")
