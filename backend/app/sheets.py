"""Worksheets: the forms a field crew or laboratory fills in for each kind of test, with
their calculation, the standards they follow and an example data set.

Field worksheets are stored as field activities (``data`` holds the worksheet), laboratory
worksheets as the raw data of a lab test. Definitions live in sheets_field.py and
sheets_lab.py; this module only holds the shape and the lookup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .calcbase import CalcError
from .fields import F

Standard = Tuple[str, str]  # (code, title)


@dataclass
class Sheet:
    key: str
    kind: str  # "field", "lab", or "page" (a catalogue entry served by another page of the app)
    group: str  # field: general, survey, geotechnical, geophysics, geology; lab: lab
    code: str  # document number such as "03.02"
    label: str
    fields: List[F] = field(default_factory=list)
    calc: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    standards: List[Standard] = field(default_factory=list)
    example: Dict[str, Any] = field(default_factory=dict)
    help: str = ""
    link: str = ""  # for kind "page": which page of the app holds it


FIELD_GROUPS: List[Tuple[str, str, str]] = [  # value, label, document group code
    ("general", "General", "01"),
    ("survey", "Geodesy & mapping", "02"),
    ("geotechnical", "Geotechnical", "03"),
    ("geophysics", "Geophysics", "04"),
    ("geology", "Geology", "06"),
]

_REGISTRY: Dict[Tuple[str, str], Sheet] = {}
_ORDER: List[Sheet] = []


def register(*sheets: Sheet) -> None:
    for sheet in sheets:
        _REGISTRY[(sheet.kind, sheet.key)] = sheet
        _ORDER.append(sheet)


def get(kind: str, key: str) -> Optional[Sheet]:
    _load()
    return _REGISTRY.get((kind, key))


def all_sheets(kind: Optional[str] = None) -> List[Sheet]:
    _load()
    return [s for s in _ORDER if kind is None or s.kind == kind]


_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import sheets_field, sheets_lab  # noqa: F401  (they call register)


def calculate(kind: str, key: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the worksheet calculation; None when the worksheet has none or no data."""
    sheet = get(kind, key)
    if sheet is None or sheet.calc is None or not data:
        return None
    try:
        return sheet.calc(data)
    except CalcError:
        raise
    except (ValueError, ZeroDivisionError) as exc:
        raise CalcError(str(exc) or "The data cannot be calculated") from exc



def catalog() -> List[Dict[str, Any]]:
    """Worksheet list for the browser: code, name, standards, example, whether it calculates."""
    return [{
        "key": s.key, "kind": s.kind, "group": s.group, "code": s.code, "label": s.label,
        "standards": [list(x) for x in s.standards], "example": s.example, "calc": s.calc is not None,
        "help": s.help, "link": s.link,
    } for s in all_sheets()]
