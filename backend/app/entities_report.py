"""Client report templates, versions and the approval flow on ``project_reports``, and the
integrity seal on reports and authorised laboratory results (see client_reports.py, seals.py).

Imported at the end of entities.py. Older reports stay valid: they have no template (the print
uses their summary, scope and recommendations as before), start the flow as drafts and get
version 1 on their next save.
"""
from __future__ import annotations

from typing import Any, Dict

from . import client_reports, report_templates
from .entities import ENTITIES, F, _add
from .fields import ACTION_HOOKS, COMPUTE_HOOKS

_report = ENTITIES["project_reports"]
_report.workflow = True
_report.reviewers = ("admin", "manager")
_report.approvers = ("admin", "manager")

_SECTION_FIELDS = [
    F("key", "text", "Key", maxlen=40),
    F("title", "text", "Section", required=True, maxlen=200),
    F("source", "text", "Content from", maxlen=200),
    F("include", "bool", "Include", default=True),
    F("text", "longtext", "Text", maxlen=8000),
]
_ANNEX_FIELDS = [
    F("kind", "select", "Annex", required=True, options=report_templates.ANNEX_KINDS),
    F("title", "text", "Title", required=True, maxlen=200),
    F("ref", "text", "Record / file", maxlen=80),
]

_new_fields = {
    "template": F("template", "select", "Project type (template)", options=report_templates.TEMPLATE_OPTIONS, list=True,
                  help="Sets the section outline; each section is filled from the project's data where the app has it."),
    "supersedes_id": F("supersedes_id", "ref", "Replaces version", ref="project_reports",
                       help="A new version of an approved report keeps its number; the earlier version becomes superseded when this one is approved."),
    "revision_note": F("revision_note", "longtext", "Revision note", maxlen=2000, help="What changed in this version."),
    "sections": F("sections", "items", "Sections", max_items=40, fields=_SECTION_FIELDS),
    "annexes": F("annexes", "items", "Annexes", max_items=80, fields=_ANNEX_FIELDS),
    "references": F("references", "multiselect", "References (standards)", options=report_templates.reference_catalog(),
                    help="Printed as the list of references."),
    "other_references": F("other_references", "longtext", "Other references", maxlen=4000,
                          help="Textbooks, papers and earlier reports, one per line."),
}
_after = {"date": ["template", "supersedes_id", "revision_note"], "recommendations": ["sections", "annexes", "references", "other_references"]}
_fields = []
for _f in _report.fields:
    if _f.name == "status":
        _f.readonly = True
        _f.options = list(_f.options or []) + [("superseded", "Superseded by a newer version")]
    _fields.append(_f)
    for _name in _after.get(_f.name, []):
        _fields.append(_new_fields[_name])
_report.fields = _fields + [
    F("version", "int", "Version", readonly=True, list=True),
    F("family_id", "text", "Report family", readonly=True),
    F("superseded_by", "text", "Superseded by", readonly=True),
    F("seal_code", "text", "Seal code", readonly=True),
    F("seal_hash", "text", "SHA-256", readonly=True),
    F("sealed_at", "text", "Sealed on", readonly=True),
]
_add(_report)  # adds the approval fields

_lab = ENTITIES["lab_tests"]
_lab.fields += [
    F("seal_code", "text", "Seal code", readonly=True, section="Quality"),
    F("seal_hash", "text", "SHA-256", readonly=True, section="Quality"),
    F("sealed_at", "text", "Sealed on", readonly=True, section="Quality"),
]

COMPUTE_HOOKS["project_reports"] = client_reports.compute_report
ACTION_HOOKS["project_reports"] = client_reports.on_workflow

_lab_hook = COMPUTE_HOOKS.get("lab_tests")


def _lab_tests(record: Dict[str, Any]) -> None:
    if _lab_hook is not None:
        _lab_hook(record)
    client_reports.seal_lab_test(record)


COMPUTE_HOOKS["lab_tests"] = _lab_tests
