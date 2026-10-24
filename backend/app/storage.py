"""CSV-backed storage for borehole reports.

The CSV text lives in a file (default) or in Postgres (DATABASE_URL), see docstore.py.
Every read-modify-write holds the document lock and writes are atomic, so concurrent
requests or a crash mid-write can never leave a half-written ``reports.csv`` behind.
"""
from __future__ import annotations

import csv
import io
import pathlib
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import docstore
from .docstore import DATA_PATH, atomic_write_file  # noqa: F401  (re-exported)

DOC = "reports.csv"
FILE = docstore.path_for(DOC)  # only meaningful in file mode

HEADERS: Sequence[str] = (
    "BoreholeID",
    "ProjectName",
    "SiteName",
    "Latitude",
    "Longitude",
    "GroundElevation_mRL",
    "StartDate",
    "EndDate",
    "DrillingMethod",
    "DrillRig",
    "CoreSize",
    "BoreholeDiameter_mm",
    "TargetDepth_m",
    "FinalDepth_m",
    "CasingInstalled_mm",
    "GroundwaterDepth_m",
    "GroundwaterEncountered",
    "SoilDescription",
    "USCS_Class",
    "Avg_SPT_N60",
    "Contractor",
    "LoggingGeologist",
    "Remarks",
    "SubmittedBy",
)

# Fields a client may never set or change directly.
SERVER_MANAGED_FIELDS = frozenset({"BoreholeID", "SubmittedBy"})
EDITABLE_FIELDS = tuple(h for h in HEADERS if h not in SERVER_MANAGED_FIELDS)



class DuplicateReportError(Exception):
    """A report with the same BoreholeID already exists."""


class SchemaMismatchError(RuntimeError):
    """The existing reports.csv has columns this app does not know about."""


class AmbiguousReportError(Exception):
    """Several rows match the BoreholeID only case-insensitively (legacy/hand-edited CSV)."""


def atomic_write_text(path: pathlib.Path, content: str, *, mode: Optional[int] = None) -> None:
    """Backwards-compatible alias of docstore.atomic_write_file."""
    atomic_write_file(path, content, mode=mode)


def _to_row(report: Dict[str, Any]) -> Dict[str, Any]:
    row = {key: "" for key in HEADERS}
    for key in HEADERS:
        if key in report and report[key] is not None:
            row[key] = report[key]
    return row


def _render_csv(items: List[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in items:
        writer.writerow(_to_row(row))
    return buffer.getvalue()


def _read_raw() -> tuple[Sequence[str], List[Dict[str, Any]]]:
    text = docstore.read_text(DOC)
    if text is None:
        return [], []
    # NUL bytes (from older versions or hand edits) make csv raise on Python 3.10.
    reader = csv.DictReader(io.StringIO(text.replace("\x00", "")))
    header = list(reader.fieldnames or [])
    items = [dict(row) for row in reader]
    return header, items


def _check_schema(header: Sequence[str]) -> None:
    unknown = [col for col in header if col not in HEADERS]
    if unknown:
        raise SchemaMismatchError(
            "Existing reports.csv has unknown columns "
            f"({', '.join(unknown)}). Migrate or remove the file before continuing."
        )


def load_reports() -> List[Dict[str, Any]]:
    # A single read is consistent on its own (one SELECT / an atomically replaced
    # file), so readers do not queue behind each other; only writers take the lock.
    header, items = _read_raw()
    if header:
        _check_schema(header)
    return [_to_row(row) for row in items]


def _key(value: Any) -> str:
    return str(value or "").strip()


def _find_index(items: List[Dict[str, Any]], borehole_id: str) -> Optional[int]:
    """Exact match first; otherwise a single case-insensitive match.

    New IDs are unique case-insensitively, but a hand-edited CSV may hold e.g. ``bh-9``
    and ``BH-9``: then only the exact spelling is accepted, never "all of them".
    """
    wanted = _key(borehole_id)
    for index, row in enumerate(items):
        if _key(row.get("BoreholeID")) == wanted:
            return index
    folded = [i for i, row in enumerate(items) if _key(row.get("BoreholeID")).lower() == wanted.lower()]
    if len(folded) > 1:
        raise AmbiguousReportError(wanted)
    return folded[0] if folded else None


def _read_checked() -> List[Dict[str, Any]]:
    header, items = _read_raw()
    if header:
        _check_schema(header)
    return items


def get_report(borehole_id: str) -> Optional[Dict[str, Any]]:
    items = _read_checked()
    index = _find_index(items, borehole_id)
    return None if index is None else _to_row(items[index])


def save_report(report: Dict[str, Any], submitted_by: str | None = None) -> None:
    """Append a new report. Raises DuplicateReportError if the ID is taken."""
    payload = dict(report)
    if submitted_by:
        payload["SubmittedBy"] = submitted_by
    new_id = _key(payload.get("BoreholeID")).lower()
    with docstore.lock(DOC):
        items = _read_checked()
        if any(_key(r.get("BoreholeID")).lower() == new_id for r in items):
            raise DuplicateReportError(new_id)
        items.append(payload)
        docstore.write_text(DOC, _render_csv(items))


def _write_reports(items: List[Dict[str, Any]]) -> None:
    docstore.write_text(DOC, _render_csv(items))


Authorizer = Callable[[Dict[str, Any]], None]


def delete_report(borehole_id: str, authorize: Optional[Authorizer] = None) -> bool:
    """Remove the one report matching BoreholeID. Returns True if deleted.

    ``authorize`` is called with the row while the lock is held (it may raise), so the
    row that was checked is exactly the row that is removed.
    """
    with docstore.lock(DOC):
        items = _read_checked()
        index = _find_index(items, borehole_id)
        if index is None:
            return False
        if authorize:
            authorize(_to_row(items[index]))
        del items[index]
        _write_reports(items)
        return True


def update_report(
    borehole_id: str,
    updates: Dict[str, Any],
    authorize: Optional[Authorizer] = None,
    validate: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> bool:
    """Update editable fields of the report matching BoreholeID.

    ``validate`` receives the merged row before it is written (it may raise).
    """
    safe_updates = {k: v for k, v in (updates or {}).items() if k in EDITABLE_FIELDS}
    with docstore.lock(DOC):
        items = _read_checked()
        index = _find_index(items, borehole_id)
        if index is None:
            return False
        if authorize:
            authorize(_to_row(items[index]))
        merged = dict(items[index])
        merged.update(safe_updates)
        if validate:
            validate(_to_row(merged))
        items[index] = merged
        _write_reports(items)
        return True
