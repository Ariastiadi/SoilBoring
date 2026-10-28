"""Field and entity definitions shared by the record kinds and the worksheets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

ALL_ROLES = ("admin", "manager", "general", "lab", "finance")
COMMERCIAL = ("admin", "manager", "finance")

Option = Tuple[str, str]  # (stored value, English label)


@dataclass
class F:
    name: str
    type: str  # text, longtext, number, int, money, percent, date, select, multiselect, ref, user, email, bool, items, files, json
    label: str
    required: bool = False
    options: Optional[List[Any]] = None  # [(value, label)] or [(value, label, group)]
    options_filter: Optional[str] = None  # show only options whose group equals this field's value
    ref: Optional[str] = None  # entity name for type "ref"
    min: Optional[float] = None
    max: Optional[float] = None
    maxlen: int = 200
    help: str = ""
    fields: Optional[List["F"]] = None  # sub-fields for "items"
    max_items: int = 200
    list: bool = False  # shown as a column in lists
    readonly: bool = False  # computed by the server
    default: Any = None
    variants_by: Optional[str] = None  # for "json": which field picks the variant
    variants: Optional[Dict[str, List["F"]]] = None
    section: str = ""
    private: bool = False  # only shown to admin, manager and finance


@dataclass
class Entity:
    name: str
    label: str
    label_one: str
    fields: List[F]
    title: str  # field used as the record's title
    read: Tuple[str, ...] = ALL_ROLES
    write: Tuple[str, ...] = ("admin", "manager")
    own_write: Tuple[str, ...] = ()  # roles that may change only records they created
    number_prefix: str = ""  # automatic numbers such as INV-2026-001
    number_field: str = ""
    singleton: bool = False
    group: str = ""
    sort: str = "-created_at"
    # Approval flow (Konseptor → Pengulas → Pemutus): draft → submitted → reviewed → approved.
    workflow: bool = False
    reviewers: Tuple[str, ...] = ("admin", "manager")
    approvers: Tuple[str, ...] = ("admin",)
    # Roles that see only their own records: created by them, or naming them in owner_field.
    own_read: Tuple[str, ...] = ()
    owner_field: str = ""

    def field(self, name: str) -> Optional[F]:
        return next((f for f in self.fields if f.name == name), None)


# Calculations of the ERP modules, registered by their entity files: entity name -> function(record).
# Called by records.compute() on every save, inside the entity lock; a hook may read other records.
COMPUTE_HOOKS: Dict[str, Callable[[Dict[str, Any]], None]] = {}

# Record locks of the ERP modules outside the approval flow: entity name -> function(record, role, action) returning
# why the record cannot be changed ("edit") or deleted ("delete") now, or None (e.g. a field package sent to the office).
# Before a delete, a guard may also remove dependent records that were generated and never used (inside the entity lock).
LOCK_HOOKS: Dict[str, Callable[[Dict[str, Any], str, str], Optional[str]]] = {}
# Steps of the approval flow, registered by entity files: entity name -> function(record, action, email, role).
# Called by workflow.act() inside the entity lock after the new state is set and before the record is
# written; it may change the record or refuse the step (workflow.WorkflowError).
ACTION_HOOKS: Dict[str, Callable[[Dict[str, Any], str, str, str], None]] = {}
