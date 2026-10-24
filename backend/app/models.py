from __future__ import annotations

from datetime import datetime
import re
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


_NUMERIC_FIELDS = (
    "Latitude",
    "Longitude",
    "GroundElevation_mRL",
    "BoreholeDiameter_mm",
    "TargetDepth_m",
    "FinalDepth_m",
    "CasingInstalled_mm",
    "GroundwaterDepth_m",
    "Avg_SPT_N60",
)
_DATE_FIELDS = ("StartDate", "EndDate")
_TEXT_LIMITS = {
    "BoreholeID": 64,
    "ProjectName": 200,
    "SiteName": 200,
    "DrillingMethod": 100,
    "USCS_Class": 20,
    "Contractor": 200,
    "LoggingGeologist": 200,
    "SoilDescription": 2000,
    "Remarks": 4000,
}


# Characters that cannot travel safely in a URL path segment or a CSV-driven UI.
_BAD_ID_CHARS = re.compile(r"[/\\?#%\x00-\x1f\x7f]")
_REQUIRED_FIELDS = (
    "ProjectName", "SiteName", "StartDate", "EndDate", "DrillingMethod", "FinalDepth_m", "Contractor",
)

EMAIL_MAX_LENGTH = 254
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")


def normalize_email(value: Any) -> str:
    """One rule for every place an email enters the app (login, Users tab, CLI, env).

    Deliberately simple: intranet domains such as ``ops@site.local`` must work.
    """
    text = str(value or "").strip()
    if not text or len(text) > EMAIL_MAX_LENGTH or not _EMAIL_RE.match(text):
        raise ValueError("Enter a valid email address (name@domain)")
    return text


Email = Annotated[str, AfterValidator(normalize_email)]


# Control characters (except tab and newlines) break CSV readers and spreadsheets.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        # Lists/objects are left alone so field validation rejects them (no "[]" text).
        return value
    return _CONTROL_CHARS.sub("", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


class ReportBase(BaseModel):
    """Shared validation for creating and editing a report.

    Values are kept as strings because that is how they live in the CSV.
    Unknown keys are dropped, so clients can never inject extra columns or
    overwrite server-managed fields such as ``SubmittedBy``.
    """

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {key: _clean(value) for key, value in data.items()}

    @field_validator(*_NUMERIC_FIELDS, mode="after", check_fields=False)
    @classmethod
    def _numeric(cls, value: Optional[str], info) -> Optional[str]:
        if value in (None, ""):
            return value
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{info.field_name} must be a number") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{info.field_name} must be a finite number")
        name = info.field_name
        if name == "Latitude" and not -90 <= number <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if name == "Longitude" and not -180 <= number <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        if name in {"BoreholeDiameter_mm", "CasingInstalled_mm"} and number < 0:
            raise ValueError(f"{name} cannot be negative")
        if name in {"TargetDepth_m", "FinalDepth_m", "GroundwaterDepth_m", "Avg_SPT_N60"} and number < 0:
            raise ValueError(f"{name} cannot be negative")
        return value

    @field_validator(*_DATE_FIELDS, mode="after", check_fields=False)
    @classmethod
    def _date(cls, value: Optional[str], info) -> Optional[str]:
        if value in (None, ""):
            return value
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{info.field_name} must use YYYY-MM-DD") from exc
        return value

    @field_validator("GroundwaterEncountered", mode="before", check_fields=False)
    @classmethod
    def _bool_text(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return "True" if value else "False"
        text = str(value).strip().lower()
        if text in {"true", "yes", "1"}:
            return "True"
        if text in {"false", "no", "0"}:
            return "False"
        raise ValueError("GroundwaterEncountered must be true or false")

    @field_validator(*_TEXT_LIMITS.keys(), mode="after", check_fields=False)
    @classmethod
    def _length(cls, value: Optional[str], info) -> Optional[str]:
        limit = _TEXT_LIMITS[info.field_name]
        if value is not None and len(value) > limit:
            raise ValueError(f"{info.field_name} must be at most {limit} characters")
        return value

    def _check_cross_fields(self, start: Optional[str], end: Optional[str]) -> None:
        if start and end and datetime.strptime(start, "%Y-%m-%d") > datetime.strptime(end, "%Y-%m-%d"):
            raise ValueError("StartDate must not be after EndDate")


class Report(ReportBase):
    """Payload for creating a report."""

    BoreholeID: str = Field(min_length=1)

    @field_validator("BoreholeID", mode="after")
    @classmethod
    def _id_chars(cls, value: str) -> str:
        if _BAD_ID_CHARS.search(value):
            raise ValueError("BoreholeID cannot contain / \\ ? # % or control characters")
        if value in {".", ".."}:
            # Browsers rewrite these as path segments, so the log could never be edited.
            raise ValueError('BoreholeID cannot be "." or ".."')
        return value
    ProjectName: str = Field(min_length=1)
    SiteName: str = Field(min_length=1)
    Latitude: Optional[str] = None
    Longitude: Optional[str] = None
    GroundElevation_mRL: Optional[str] = None
    StartDate: str = Field(min_length=1)
    EndDate: str = Field(min_length=1)
    DrillingMethod: str = Field(min_length=1)
    BoreholeDiameter_mm: Optional[str] = None
    TargetDepth_m: Optional[str] = None
    FinalDepth_m: str = Field(min_length=1)
    CasingInstalled_mm: Optional[str] = None
    GroundwaterDepth_m: Optional[str] = None
    GroundwaterEncountered: Optional[str] = None
    SoilDescription: Optional[str] = None
    USCS_Class: Optional[str] = None
    Avg_SPT_N60: Optional[str] = None
    Contractor: str = Field(min_length=1)
    LoggingGeologist: Optional[str] = None
    Remarks: Optional[str] = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> "Report":
        self._check_cross_fields(self.StartDate, self.EndDate)
        return self


class ReportUpdate(ReportBase):
    """Partial payload for editing a report; BoreholeID/SubmittedBy are ignored."""

    ProjectName: Optional[str] = Field(default=None, min_length=1)
    SiteName: Optional[str] = Field(default=None, min_length=1)
    Latitude: Optional[str] = None
    Longitude: Optional[str] = None
    GroundElevation_mRL: Optional[str] = None
    StartDate: Optional[str] = Field(default=None, min_length=1)
    EndDate: Optional[str] = Field(default=None, min_length=1)
    DrillingMethod: Optional[str] = Field(default=None, min_length=1)
    BoreholeDiameter_mm: Optional[str] = None
    TargetDepth_m: Optional[str] = None
    FinalDepth_m: Optional[str] = Field(default=None, min_length=1)
    CasingInstalled_mm: Optional[str] = None
    GroundwaterDepth_m: Optional[str] = None
    GroundwaterEncountered: Optional[str] = None
    SoilDescription: Optional[str] = None
    USCS_Class: Optional[str] = None
    Avg_SPT_N60: Optional[str] = None
    Contractor: Optional[str] = Field(default=None, min_length=1)
    LoggingGeologist: Optional[str] = None
    Remarks: Optional[str] = None

    @field_validator(*_REQUIRED_FIELDS, mode="before")
    @classmethod
    def _not_null(cls, value: Any, info) -> Any:
        # Leaving a required field out is fine (partial update); sending null would blank it.
        if value is None:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value

    @model_validator(mode="after")
    def _dates_in_order(self) -> "ReportUpdate":
        self._check_cross_fields(self.StartDate, self.EndDate)
        return self


MAX_QUESTION_CHARS = 2000
MAX_CONTEXT_CHARS = 8000
MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 4000


class HistoryTurn(BaseModel):
    # Only user/assistant turns are accepted, so a client cannot inject a
    # "system" message into the model conversation.
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_HISTORY_CHARS)


class Query(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    context: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)
    history: Optional[List[HistoryTurn]] = Field(default=None, max_length=MAX_HISTORY_TURNS)


class Summary(BaseModel):
    period: str
    text: str


def dump_report(model: BaseModel, *, exclude_unset: bool = False) -> Dict[str, Any]:
    return model.model_dump(exclude_unset=exclude_unset)
