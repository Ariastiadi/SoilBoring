"""Depth-by-depth data for each borehole: strata, SPT tests, samples, core runs and photos.

The daily log (reports.csv) keeps one summary row per borehole. Everything that is
recorded per depth lives here, keyed by the exact BoreholeID of that row:

* ``details.json`` - {BoreholeID: {"layers": [...], "spt": [...], "samples": [...],
  "core": [...], "photos": [...], "updated_at": ..., "updated_by": ...}}
* ``photo-<id>.b64`` - one document per photo (base64 JPEG/PNG/WebP), so the details
  document stays small.

Both are stored through docstore (files or Postgres), like the rest of the app.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import docstore

DOC = "details.json"
MAX_DEPTH_M = 1000.0
MAX_ROWS = 300
MAX_PHOTOS = 30
MAX_PHOTO_BYTES = 2_000_000
PHOTO_TYPES = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}

# AGS4 SAMP_TYPE codes offered in the app (standard ABBR list).
SAMPLE_TYPES: Dict[str, str] = {
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

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _text(value: Optional[str], limit: int) -> str:
    text = _CONTROL.sub("", str(value or "")).strip()
    if len(text) > limit:
        raise ValueError(f"must be at most {limit} characters")
    return text


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Layer(_Row):
    top: float = Field(ge=0, le=MAX_DEPTH_M)
    base: float = Field(gt=0, le=MAX_DEPTH_M)
    uscs: str = ""
    description: str = ""

    @field_validator("uscs", mode="before")
    @classmethod
    def _uscs(cls, value: Any) -> str:
        return _text(value, 20).upper()

    @field_validator("description", mode="before")
    @classmethod
    def _desc(cls, value: Any) -> str:
        return _text(value, 1000)

    @model_validator(mode="after")
    def _order(self) -> "Layer":
        if self.base <= self.top:
            raise ValueError("layer base must be deeper than its top")
        return self


class SPTTest(_Row):
    """One SPT: blows for the 150 mm seating drive and the two 150 mm test increments.

    N = blows of the two test increments. When the test was stopped early (refusal, e.g.
    50 blows), ``penetration_mm`` is the test-drive penetration actually reached.
    """

    depth: float = Field(ge=0, le=MAX_DEPTH_M)
    seat: int = Field(ge=0, le=200)
    inc1: int = Field(ge=0, le=200)
    inc2: Optional[int] = Field(default=None, ge=0, le=200)
    penetration_mm: Optional[int] = Field(default=None, ge=1, le=300)
    remarks: str = ""

    @field_validator("remarks", mode="before")
    @classmethod
    def _rem(cls, value: Any) -> str:
        return _text(value, 300)

    @property
    def n(self) -> int:
        return self.inc1 + (self.inc2 or 0)

    @property
    def refusal(self) -> bool:
        return self.penetration_mm is not None and self.penetration_mm < 300

    def reported(self) -> str:
        if self.refusal:
            return f"{self.n}/{self.penetration_mm}mm"
        return f"N={self.n}"


class Sample(_Row):
    top: float = Field(ge=0, le=MAX_DEPTH_M)
    base: Optional[float] = Field(default=None, gt=0, le=MAX_DEPTH_M)
    type: str
    ref: str = ""
    remarks: str = ""

    @field_validator("ref", mode="before")
    @classmethod
    def _ref(cls, value: Any) -> str:
        return _text(value, 20)

    @field_validator("remarks", mode="before")
    @classmethod
    def _rem(cls, value: Any) -> str:
        return _text(value, 300)

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, value: Any) -> str:
        code = str(value or "").strip().upper()
        if code not in SAMPLE_TYPES:
            raise ValueError(f"sample type must be one of {', '.join(SAMPLE_TYPES)}")
        return code

    @model_validator(mode="after")
    def _order(self) -> "Sample":
        if self.base is not None and self.base <= self.top:
            raise ValueError("sample base must be deeper than its top")
        return self


class CoreRun(_Row):
    top: float = Field(ge=0, le=MAX_DEPTH_M)
    base: float = Field(gt=0, le=MAX_DEPTH_M)
    tcr: Optional[float] = Field(default=None, ge=0, le=100)
    scr: Optional[float] = Field(default=None, ge=0, le=100)
    rqd: Optional[float] = Field(default=None, ge=0, le=100)
    remarks: str = ""

    @field_validator("remarks", mode="before")
    @classmethod
    def _rem(cls, value: Any) -> str:
        return _text(value, 300)

    @model_validator(mode="after")
    def _check(self) -> "CoreRun":
        if self.base <= self.top:
            raise ValueError("core run base must be deeper than its top")
        if self.tcr is not None and self.scr is not None and self.scr > self.tcr:
            raise ValueError("SCR cannot be more than TCR")
        if self.scr is not None and self.rqd is not None and self.rqd > self.scr:
            raise ValueError("RQD cannot be more than SCR")
        return self


def _no_overlap(rows: List[Any], what: str) -> None:
    ordered = sorted(rows, key=lambda r: (r.top, r.base))
    for before, after in zip(ordered, ordered[1:]):
        if after.top < before.base - 1e-9:
            raise ValueError(f"{what} {before.top:g}-{before.base:g} m and {after.top:g}-{after.base:g} m overlap")


class DetailsIn(BaseModel):
    """What the client sends; photos are managed through their own endpoints."""

    model_config = ConfigDict(extra="ignore")

    layers: List[Layer] = Field(default_factory=list, max_length=MAX_ROWS)
    spt: List[SPTTest] = Field(default_factory=list, max_length=MAX_ROWS)
    samples: List[Sample] = Field(default_factory=list, max_length=MAX_ROWS)
    core: List[CoreRun] = Field(default_factory=list, max_length=MAX_ROWS)

    @model_validator(mode="after")
    def _consistent(self) -> "DetailsIn":
        _no_overlap(self.layers, "Layers")
        _no_overlap(self.core, "Core runs")
        depths = [round(t.depth, 3) for t in self.spt]
        if len(depths) != len(set(depths)):
            raise ValueError("Two SPT tests have the same depth")
        refs = [s.ref.lower() for s in self.samples if s.ref]
        if len(refs) != len(set(refs)):
            raise ValueError("Two samples have the same reference")
        self.layers.sort(key=lambda r: r.top)
        self.spt.sort(key=lambda r: r.depth)
        self.samples.sort(key=lambda r: (r.top, r.ref))
        self.core.sort(key=lambda r: r.top)
        return self


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_all() -> Dict[str, Dict[str, Any]]:
    text = docstore.read_text(DOC)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_all(data: Dict[str, Dict[str, Any]]) -> None:
    docstore.write_text(DOC, json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _empty() -> Dict[str, Any]:
    return {"layers": [], "spt": [], "samples": [], "core": [], "photos": []}


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty()
    out.update({k: v for k, v in entry.items() if k in out or k in ("updated_at", "updated_by")})
    for test in out["spt"]:
        parsed = SPTTest.model_validate(test)
        test["n"] = parsed.n
        test["reported"] = parsed.reported()
    return out


def get_details(borehole_id: str) -> Dict[str, Any]:
    return _public(_load_all().get(borehole_id, {}))


def all_details() -> Dict[str, Dict[str, Any]]:
    return {key: _public(value) for key, value in _load_all().items()}


def save_details(borehole_id: str, details: DetailsIn, user_email: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Replace the depth data of one borehole; returns (before, after) for the audit log."""
    with docstore.lock(DOC):
        data = _load_all()
        before = _public(data.get(borehole_id, {}))
        entry = dict(data.get(borehole_id, {}))
        entry.update(details.model_dump())
        entry.setdefault("photos", [])
        entry["updated_at"] = _now()
        entry["updated_by"] = user_email
        data[borehole_id] = entry
        _save_all(data)
    return before, _public(entry)


def delete_details(borehole_id: str) -> None:
    """Remove the depth data and photos of a deleted borehole."""
    with docstore.lock(DOC):
        data = _load_all()
        entry = data.pop(borehole_id, None)
        if entry is None:
            return
        _save_all(data)
    for photo in entry.get("photos", []):
        docstore.delete(_photo_doc(photo.get("id", "")))


# --------------------------------------------------------------------------- #
# Photos
# --------------------------------------------------------------------------- #

_PHOTO_ID = re.compile(r"^[a-f0-9]{24}$")


def _photo_doc(photo_id: str) -> str:
    if not _PHOTO_ID.match(photo_id or ""):
        raise ValueError("bad photo id")
    return f"photo-{photo_id}.b64"


class PhotoIn(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    data_base64: str = Field(min_length=8, max_length=MAX_PHOTO_BYTES * 4 // 3 + 16)
    caption: str = ""
    depth: Optional[float] = Field(default=None, ge=0, le=MAX_DEPTH_M)

    @field_validator("caption", mode="before")
    @classmethod
    def _cap(cls, value: Any) -> str:
        return _text(value, 200)

    def decoded(self) -> bytes:
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("photo data is not valid base64") from exc
        if len(raw) > MAX_PHOTO_BYTES:
            raise ValueError("photo is larger than 2 MB")
        magic = PHOTO_TYPES[self.content_type]
        if not raw.startswith(magic) or (self.content_type == "image/webp" and raw[8:12] != b"WEBP"):
            raise ValueError("photo content does not match its type")
        return raw


class PhotoLimitError(Exception):
    pass


def add_photo(borehole_id: str, photo: PhotoIn, user_email: str) -> Dict[str, Any]:
    raw = photo.decoded()
    photo_id = secrets.token_hex(12)
    meta = {
        "id": photo_id,
        "caption": photo.caption,
        "depth": photo.depth,
        "content_type": photo.content_type,
        "size": len(raw),
        "added_at": _now(),
        "added_by": user_email,
    }
    with docstore.lock(DOC):
        data = _load_all()
        entry = data.setdefault(borehole_id, _empty())
        photos = entry.setdefault("photos", [])
        if len(photos) >= MAX_PHOTOS:
            raise PhotoLimitError(f"A borehole can have at most {MAX_PHOTOS} photos")
        docstore.write_text(_photo_doc(photo_id), json.dumps({"type": photo.content_type, "data": base64.b64encode(raw).decode()}))
        photos.append(meta)
        _save_all(data)
    return meta


def find_photo(photo_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(BoreholeID, metadata) of a photo, or None."""
    if not _PHOTO_ID.match(photo_id or ""):
        return None
    for borehole_id, entry in _load_all().items():
        for meta in entry.get("photos", []):
            if meta.get("id") == photo_id:
                return borehole_id, meta
    return None


def read_photo(photo_id: str) -> Optional[Tuple[str, bytes]]:
    text = docstore.read_text(_photo_doc(photo_id))
    if not text:
        return None
    try:
        doc = json.loads(text)
        return str(doc["type"]), base64.b64decode(doc["data"])
    except (ValueError, KeyError, binascii.Error):
        return None


def delete_photo(photo_id: str) -> Optional[Dict[str, Any]]:
    with docstore.lock(DOC):
        data = _load_all()
        for entry in data.values():
            photos = entry.get("photos", [])
            for index, meta in enumerate(photos):
                if meta.get("id") == photo_id:
                    del photos[index]
                    _save_all(data)
                    docstore.delete(_photo_doc(photo_id))
                    return meta
    return None
