"""CSV-backed storage for borehole reports.

All reads/writes go through a process-wide lock and writes are atomic
(temp file + ``os.replace``) so concurrent requests or a crash mid-write can
never leave a half-written ``reports.csv`` behind.
"""
from __future__ import annotations

import csv
import io
import os
import pathlib
import tempfile
import threading
from typing import Any, Dict, List, Optional, Sequence


DATA_PATH = pathlib.Path(os.environ.get("DATA_DIR", "data"))
DATA_PATH.mkdir(parents=True, exist_ok=True)

FILE = DATA_PATH / "reports.csv"

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

_LOCK = threading.RLock()


class DuplicateReportError(Exception):
    """A report with the same BoreholeID already exists."""


class SchemaMismatchError(RuntimeError):
    """The existing reports.csv has columns this app does not know about."""


def _default_mode(path: pathlib.Path) -> int:
    """Keep an existing file's permissions; new data files are readable (0644) like before."""
    try:
        return os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def atomic_write_text(path: pathlib.Path, content: str, *, mode: Optional[int] = None) -> None:
    """Write ``content`` to ``path`` atomically (never leaves a partial file).

    ``mode`` is for sensitive files (users.json, the token secret); other files keep
    their current permissions so host-side backups and spreadsheets can still read them.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = _default_mode(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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
    if not FILE.exists():
        return [], []
    with FILE.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
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
    with _LOCK:
        header, items = _read_raw()
    if header:
        _check_schema(header)
    return [_to_row(row) for row in items]


def get_report(borehole_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(borehole_id).strip().lower()
    for row in load_reports():
        if str(row.get("BoreholeID", "")).strip().lower() == wanted:
            return row
    return None


def save_report(report: Dict[str, Any], submitted_by: str | None = None) -> None:
    """Append a new report. Raises DuplicateReportError if the ID is taken."""
    payload = dict(report)
    if submitted_by:
        payload["SubmittedBy"] = submitted_by
    new_id = str(payload.get("BoreholeID", "")).strip().lower()
    with _LOCK:
        header, items = _read_raw()
        if header:
            _check_schema(header)
        if any(str(r.get("BoreholeID", "")).strip().lower() == new_id for r in items):
            raise DuplicateReportError(new_id)
        items.append(payload)
        atomic_write_text(FILE, _render_csv(items))


def _write_reports(items: List[Dict[str, Any]]) -> None:
    atomic_write_text(FILE, _render_csv(items))


def delete_report(borehole_id: str) -> bool:
    """Remove the report matching the BoreholeID. Returns True if deleted."""
    wanted = str(borehole_id).strip().lower()
    with _LOCK:
        header, items = _read_raw()
        if header:
            _check_schema(header)
        remaining = [r for r in items if str(r.get("BoreholeID", "")).strip().lower() != wanted]
        if len(remaining) == len(items):
            return False
        _write_reports(remaining)
        return True


def update_report(borehole_id: str, updates: Dict[str, Any]) -> bool:
    """Update editable fields of the report matching BoreholeID."""
    wanted = str(borehole_id).strip().lower()
    safe_updates = {k: v for k, v in (updates or {}).items() if k in EDITABLE_FIELDS}
    with _LOCK:
        header, items = _read_raw()
        if header:
            _check_schema(header)
        updated = False
        for row in items:
            if str(row.get("BoreholeID", "")).strip().lower() == wanted:
                row.update(safe_updates)
                updated = True
                break
        if updated:
            _write_reports(items)
        return updated
