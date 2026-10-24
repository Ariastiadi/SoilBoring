"""CSV-backed storage for borehole reports.

All reads/writes go through a process-wide lock and writes are atomic
(temp file + ``os.replace``) so concurrent requests or a crash mid-write can
never leave a half-written ``reports.csv`` behind.
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import pathlib
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence


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

_LOCK = threading.RLock()


class DuplicateReportError(Exception):
    """A report with the same BoreholeID already exists."""


class SchemaMismatchError(RuntimeError):
    """The existing reports.csv has columns this app does not know about."""


class AmbiguousReportError(Exception):
    """Several rows match the BoreholeID only case-insensitively (legacy/hand-edited CSV)."""


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
        _match_owner(tmp_name, path)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _match_owner(tmp_name: str, path: pathlib.Path) -> None:
    """When running as root (e.g. ``docker compose exec`` of the CLI), give the new file
    to the owner of the data folder, so the unprivileged app can still read it."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        owner = os.stat(path) if path.exists() else os.stat(path.parent)
        os.chown(tmp_name, owner.st_uid, owner.st_gid)
    except OSError:
        pass


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
    # utf-8-sig also accepts files saved by Excel as "CSV UTF-8" (with a BOM).
    with FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        text = handle.read()
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
    with _LOCK:
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
    with _LOCK:
        items = _read_checked()
        index = _find_index(items, borehole_id)
        return None if index is None else _to_row(items[index])


def save_report(report: Dict[str, Any], submitted_by: str | None = None) -> None:
    """Append a new report. Raises DuplicateReportError if the ID is taken."""
    payload = dict(report)
    if submitted_by:
        payload["SubmittedBy"] = submitted_by
    new_id = _key(payload.get("BoreholeID")).lower()
    with _LOCK:
        items = _read_checked()
        if any(_key(r.get("BoreholeID")).lower() == new_id for r in items):
            raise DuplicateReportError(new_id)
        items.append(payload)
        atomic_write_text(FILE, _render_csv(items))


def _write_reports(items: List[Dict[str, Any]]) -> None:
    atomic_write_text(FILE, _render_csv(items))


Authorizer = Callable[[Dict[str, Any]], None]


def delete_report(borehole_id: str, authorize: Optional[Authorizer] = None) -> bool:
    """Remove the one report matching BoreholeID. Returns True if deleted.

    ``authorize`` is called with the row while the lock is held (it may raise), so the
    row that was checked is exactly the row that is removed.
    """
    with _LOCK:
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
    with _LOCK:
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
