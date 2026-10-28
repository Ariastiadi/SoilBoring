"""Monitoring instruments with their readings (worksheet list 03.11): piezometers, groundwater wells,
inclinometers, settlement plates and extensometers. The field crew and managers enter and update
them; every other role reads them. Calculations are in monitor.py. Imported at the end of entities.py.
"""
from __future__ import annotations

from . import monitor
from .entities import Entity, F, _add
from .fields import ALL_ROLES, COMPUTE_HOOKS

_add(Entity(
    name="instruments", label="Monitoring instruments", label_one="Monitoring instrument", title="code", group="field",
    sort="code", read=ALL_ROLES, write=("admin", "manager", "general"),
    fields=[
        F("code", "text", "Instrument ID", required=True, maxlen=40, list=True, help="e.g. PZ-01, INC-02, SP-05."),
        F("type", "select", "Instrument type", required=True, list=True, options=monitor.TYPES),
        F("project_id", "ref", "Project", ref="projects", list=True),
        F("borehole_id", "text", "Borehole", maxlen=64, help="The borehole the instrument is installed in, if any."),
        F("location", "text", "Location", maxlen=200, help="e.g. embankment STA 1+250, toe of the slope."),
        F("status", "select", "Condition", default="active", options=[
            ("active", "Working"), ("damaged", "Damaged"), ("abandoned", "Abandoned")]),
        F("latitude", "number", "Latitude", min=-90, max=90, section="Installation"),
        F("longitude", "number", "Longitude", min=-180, max=180, section="Installation"),
        F("elevation", "number", "Reference level (mRL)", min=-1000, max=9000, section="Installation",
          help="Top of the pipe or casing, or the ground level the readings refer to."),
        F("install_date", "date", "Installed on", section="Installation"),
        F("depth", "number", "Tip / sensor / casing depth (m)", min=0, max=500, section="Installation"),
        F("unit", "text", "Reading unit", maxlen=20, section="Installation",
          help="e.g. m (water depth), kPa (pore pressure), mm (settlement or displacement). Inclinometers read in mm."),
        F("reading_is_depth", "bool", "Readings are depths below the reference level", section="Installation",
          help="For standpipes and wells read with a dip meter: the water level in mRL is worked out."),
        F("base_value", "number", "Base reading", section="Alarm levels", help="Empty: the first reading."),
        F("base_date", "date", "Base reading date", section="Alarm levels"),
        F("alarm_on", "select", "Alarm on", default="change", options=monitor.ALARM_ON, section="Alarm levels",
          help="Settlement and displacement: the change since the base reading. Pore pressure or water level: the reading itself."),
        F("alert_level", "number", "Alert level", section="Alarm levels",
          help="Review level: inform the engineer and read more often."),
        F("action_level", "number", "Action level", section="Alarm levels",
          help="Agreed action starts, e.g. stop filling or start the contingency plan."),
        F("rate_alert", "number", "Alert rate (unit per day)", min=0, section="Alarm levels",
          help="Optional: an alert also when the change over the last interval is this fast."),
        F("readings", "items", "Readings", max_items=3000, section="Readings", fields=[
            F("date", "date", "Date", required=True),
            F("value", "number", "Reading", required=True),
            F("note", "text", "Note", maxlen=120),
        ]),
        F("incl_input", "select", "Inclinometer values", default="cumulative", section="Readings", options=[
            ("cumulative", "Cumulative displacement (mm)"), ("incremental", "Incremental displacement per interval (mm)")]),
        F("profile", "items", "Inclinometer surveys", max_items=6000, section="Readings",
          help="One row per depth per survey date, relative to the base survey, as exported by the probe software.", fields=[
              F("date", "date", "Date", required=True),
              F("depth", "number", "Depth (m)", required=True, min=0, max=500),
              F("a", "number", "A (mm)", min=-10000, max=10000),
              F("b", "number", "B (mm)", min=-10000, max=10000),
          ]),
        F("alarm_state", "select", "Alarm", readonly=True, list=True, options=monitor.ALARM_STATES),
        F("latest_date", "date", "Last reading", readonly=True, list=True),
        F("latest_value", "number", "Latest reading", readonly=True, list=True),
        F("change", "number", "Change since the base reading", readonly=True),
        F("rate_per_day", "number", "Rate per day", readonly=True),
        F("max_change", "number", "Largest change", readonly=True),
        F("reading_count", "int", "Readings", readonly=True),
        F("results", "json", "Results", readonly=True),
        F("summary", "text", "Result", readonly=True, maxlen=300),
        F("files", "files", "Installation record & photos"),
        F("remarks", "longtext", "Remarks", maxlen=2000),
    ],
))

COMPUTE_HOOKS["instruments"] = monitor.compute_instrument
