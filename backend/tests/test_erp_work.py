"""Work coordination: project tasks with phase templates, field submissions, the crew roster and
laboratory work orders with turnaround. Expected values are worked out by hand in the comments."""
from datetime import date

from backend.app import erp_work

from .conftest import login_headers, make_user

TODAY = date(2026, 10, 26)  # a Monday
CFG = dict(erp_work.DEFAULT_SETTINGS)


def _h(client, email, role):
    return login_headers(client, *make_user(email, role=role))


def _post(client, entity, data, headers, status=201):
    res = client.post(f"/api/records/{entity}", json=data, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _put(client, entity, record, changes, headers, status=200):
    body = {k: v for k, v in record.items() if k not in ("id", "created_at", "created_by", "updated_at", "updated_by")}
    res = client.put(f"/api/records/{entity}/{record['id']}", json={**body, **changes}, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _project(client, headers, **extra):
    c = _post(client, "clients", {"name": "PT Contoh Geoteknik", "type": "private"}, headers)
    data = {"code": "WRK-1", "name": "Proyek Contoh", "client_id": c["id"], "status": "tender", "services": ["geotechnical"],
            "start_date": "2026-11-02", "end_date": "2026-12-31", **extra}
    return _post(client, "projects", data, headers)


def _tasks(client, headers, project_id):
    res = client.get(f"/api/records/tasks?project_id={project_id}", headers=headers)
    assert res.status_code == 200
    return res.json()


# --------------------------------------------------------------------------- #
# Working days, test categories
# --------------------------------------------------------------------------- #

def test_working_and_calendar_days():
    mon = date(2026, 10, 5)
    # 5 working days after Mon 5 Oct: Tue 6, Wed 7, Thu 8, Fri 9, Mon 12.
    assert erp_work.add_days(mon, 5) == date(2026, 10, 12)
    # 14 working days: 6–9 Oct (4), 12–16 (9), 19–23 (14) -> Fri 23 Oct; 14 calendar days -> 19 Oct.
    assert erp_work.add_days(mon, 14) == date(2026, 10, 23)
    assert erp_work.add_days(mon, 14, "calendar") == date(2026, 10, 19)
    # Received on a Saturday: the first working day counted is Monday.
    assert erp_work.add_days(date(2026, 10, 10), 1) == date(2026, 10, 12)
    # Weekdays after 5 Oct up to 16 Oct: 6,7,8,9,12,13,14,15,16 = 9; backwards is negative.
    assert erp_work.days_between(mon, date(2026, 10, 16)) == 9
    assert erp_work.days_between(date(2026, 10, 16), mon) == -9
    assert erp_work.days_between(mon, date(2026, 10, 28)) == 17
    assert erp_work.days_between(mon, date(2026, 10, 28), "calendar") == 23
    for n in range(0, 40):
        assert erp_work.days_between(mon, erp_work.add_days(mon, n)) == n


def test_test_categories_and_sla():
    assert erp_work.test_category("atterberg") == "index"
    assert erp_work.test_category("triaxial_cu") == "triaxial"
    assert erp_work.test_category("consolidation") == "consolidation"
    # Test types added later are placed by their key.
    assert erp_work.test_category("triaxial_cd_rock") == "triaxial"
    assert erp_work.test_category("soil_ph") == "chemical"
    assert erp_work.test_category("sulfate_content") == "chemical"
    assert erp_work.test_category("pinhole") == "other"
    assert erp_work.sla_days("moisture", CFG) == 5 and erp_work.sla_days("triaxial", CFG) == 14
    assert erp_work.sla_days("consolidation", CFG) == 21 and erp_work.sla_days("pinhole", CFG) == 10


# --------------------------------------------------------------------------- #
# Project tasks
# --------------------------------------------------------------------------- #

def test_standard_task_plan_dates():
    # 2 Nov to 31 Dec 2026 = 59 days. Reconnaissance 0–5 %: starts 2 Nov, due 2 Nov + round(2.95) = 3 days -> 5 Nov.
    # Field data 10–55 %: 2 Nov + round(5.9) = 6 -> 8 Nov, due + round(32.45) = 32 -> 4 Dec. Report due + 59 -> 31 Dec.
    # Demobilisation 55–62 %: from 4 Dec, due + round(36.58) = 37 -> 9 Dec.
    plan = {p["phase"]: p for p in erp_work.standard_task_plan(
        {"start_date": "2026-11-02", "end_date": "2026-12-31", "services": ["geotechnical"], "leader": "pm@example.com"})}
    assert list(plan) == ["reconnaissance", "mobilisation", "field_data", "processing", "analysis", "report", "demobilisation"]
    assert (plan["reconnaissance"]["start_date"], plan["reconnaissance"]["due_date"]) == ("2026-11-02", "2026-11-05")
    assert (plan["field_data"]["start_date"], plan["field_data"]["due_date"]) == ("2026-11-08", "2026-12-04")
    assert plan["report"]["due_date"] == "2026-12-31"
    assert (plan["demobilisation"]["start_date"], plan["demobilisation"]["due_date"]) == ("2026-12-04", "2026-12-09")
    assert plan["mobilisation"]["title"] == "Mobilisation – Geotechnical drilling"
    assert plan["mobilisation"]["assignee"] == "pm@example.com" and len(plan["mobilisation"]["checklist"]) == 3
    # Laboratory only: processing and report. No end date: a 60-day period (report due 60 days after the start).
    lab = erp_work.standard_task_plan({"start_date": "2026-11-02", "services": ["laboratory"]})
    assert [p["phase"] for p in lab] == ["processing", "report"] and lab[-1]["due_date"] == "2027-01-01"


def test_project_contract_creates_tasks_once(client, admin_headers):
    p = _project(client, admin_headers, services=["geotechnical", "laboratory"])
    assert _tasks(client, admin_headers, p["id"]) == []
    p = _put(client, "projects", p, {"status": "contract"}, admin_headers)
    tasks = _tasks(client, admin_headers, p["id"])
    assert len(tasks) == 7 + 2
    assert {t["template_key"] for t in tasks} >= {"geotechnical:field_data", "laboratory:report"}
    # Ongoing after contract, the button and a later re-entry never duplicate.
    p = _put(client, "projects", p, {"status": "ongoing"}, admin_headers)
    res = client.post(f"/api/erp/work/projects/{p['id']}/standard-tasks", headers=admin_headers)
    assert res.status_code == 200 and res.json() == {"created": 0, "skipped": 9}
    p = _put(client, "projects", p, {"status": "reporting"}, admin_headers)
    _put(client, "projects", p, {"status": "ongoing"}, admin_headers)
    assert len(_tasks(client, admin_headers, p["id"])) == 9
    # A service added later: only its tasks are created; the preview marks what exists.
    p = client.get(f"/api/records/projects/{p['id']}", headers=admin_headers).json()
    p = _put(client, "projects", p, {"services": ["geotechnical", "laboratory", "cpt"]}, admin_headers)
    preview = client.get(f"/api/erp/work/projects/{p['id']}/standard-tasks", headers=admin_headers).json()
    assert sum(1 for x in preview if not x["exists"]) == 7
    assert client.post(f"/api/erp/work/projects/{p['id']}/standard-tasks", headers=admin_headers).json() == {"created": 7, "skipped": 9}
    # Field staff cannot create the standard tasks.
    worker = _h(client, "field1@example.com", "general")
    assert client.post(f"/api/erp/work/projects/{p['id']}/standard-tasks", headers=worker).status_code == 403


def test_new_project_created_ongoing_gets_tasks(client, admin_headers):
    p = _project(client, admin_headers, status="ongoing", services=["analysis"])
    tasks = _tasks(client, admin_headers, p["id"])
    assert sorted(t["phase"] for t in tasks) == ["analysis", "report"]
    assert all(t["created_by"] == "admin@example.com" and t["status"] == "todo" for t in tasks)


def test_project_delete_removes_untouched_standard_tasks(client, admin_headers):
    p = _project(client, admin_headers, status="ongoing")
    assert len(_tasks(client, admin_headers, p["id"])) == 7
    assert client.delete(f"/api/records/projects/{p['id']}", headers=admin_headers).status_code == 200
    assert client.get("/api/records/tasks", headers=admin_headers).json() == []
    # Once someone works on a task, the project keeps it and cannot be deleted.
    p = _post(client, "projects", {"code": "WRK-9", "name": "Proyek Sembilan", "client_id": p["client_id"], "status": "ongoing"}, admin_headers)
    t = _tasks(client, admin_headers, p["id"])[0]
    client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "in_progress"}, headers=admin_headers)
    res = client.delete(f"/api/records/projects/{p['id']}", headers=admin_headers)
    assert res.status_code == 409 and "Task" in res.json()["detail"]
    assert len(_tasks(client, admin_headers, p["id"])) == 7


def test_task_status_by_assignee_and_permissions(client, admin_headers):
    worker = _h(client, "field1@example.com", "general")
    other = _h(client, "field2@example.com", "general")
    p = _project(client, admin_headers)
    t = _post(client, "tasks", {"title": "Bor BH-01", "project_id": p["id"], "assignee": "field1@example.com", "due_date": "2026-10-20",
                                "checklist": [{"item": "Rig set up"}, {"item": "SPT every 2 m"}]}, admin_headers)
    assert t["status"] == "todo" and t["checklist_pct"] == 0 and t["history"][0]["to"] == "todo"
    # The assignee cannot edit the task itself (created by the manager) but can change its status and ticks.
    assert client.put(f"/api/records/tasks/{t['id']}", json={"title": "x", "project_id": p["id"]}, headers=worker).status_code == 403
    res = client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "blocked", "note": "Akses lokasi banjir"}, headers=worker)
    assert res.status_code == 200, res.text
    assert res.json()["blocked_reason"] == "Akses lokasi banjir" and res.json()["history"][-1]["by"] == "field1@example.com"
    # Someone else's field user cannot.
    assert client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "done"}, headers=other).status_code == 403
    # Done with one item open: completed today, flagged.
    res = client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "done", "checklist": [True, False]}, headers=worker)
    done = res.json()
    assert done["completed_at"] == date.today().isoformat() and done["checklist_pct"] == 50 and done["blocked_reason"] == ""
    assert done["warnings"][0]["text"] == "{n} checklist items are not ticked"
    assert client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "done", "checklist": [True]}, headers=worker).status_code == 422
    assert client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "finished"}, headers=worker).status_code == 422
    # Reopened: the completion date is cleared.
    again = client.post(f"/api/erp/work/tasks/{t['id']}/status", json={"status": "in_progress"}, headers=worker).json()
    assert again["completed_at"] == "" and [h["to"] for h in again["history"]] == ["todo", "blocked", "done", "in_progress"]
    # Due before start is refused.
    assert client.post("/api/records/tasks", json={"title": "x", "project_id": p["id"], "start_date": "2026-10-10", "due_date": "2026-10-01"},
                       headers=admin_headers).status_code == 422


def test_my_tasks_overdue_first_and_summary(client, admin_headers):
    _h(client, "field1@example.com", "general")
    worker = login_headers(client, "field1@example.com", "correct-horse-1")
    p = _project(client, admin_headers)
    base = {"project_id": p["id"], "assignee": "field1@example.com"}
    _post(client, "tasks", {**base, "title": "Later", "due_date": "2099-01-10"}, admin_headers)
    _post(client, "tasks", {**base, "title": "Late", "due_date": "2020-01-10"}, admin_headers)
    _post(client, "tasks", {**base, "title": "Done late", "due_date": "2020-01-01", "status": "done"}, admin_headers)
    _post(client, "tasks", {"project_id": p["id"], "title": "Someone else", "assignee": "x@example.com", "due_date": "2020-01-01"}, admin_headers)
    mine = client.get("/api/erp/work/my-tasks", headers=worker).json()
    assert [t["title"] for t in mine] == ["Late", "Later", "Done late"]
    assert mine[0]["overdue"] and not mine[2]["overdue"] and mine[0]["project_code"] == "WRK-1"
    s = client.get("/api/erp/work/summary", headers=worker).json()
    assert s["tasks_open"] == 2 and s["tasks_overdue"] == 1 and s["lab_overdue"] is None and s["roster_warnings"] is None


# --------------------------------------------------------------------------- #
# Field submissions
# --------------------------------------------------------------------------- #

def test_field_submission_flow(client, admin_headers):
    worker = _h(client, "field1@example.com", "general")
    other = _h(client, "field2@example.com", "general")
    manager = _h(client, "pm@example.com", "manager")
    lab = _h(client, "lab1@example.com", "lab")
    p = _project(client, admin_headers, status="ongoing")
    dr = _post(client, "field_activities", {"code": "DR-2026-10-26", "type": "general", "method": "daily_report", "project_id": p["id"],
                                            "date": "2026-10-26"}, worker)
    ws = _post(client, "field_activities", {"code": "PLT-1", "type": "geotechnical", "method": "plt", "project_id": p["id"],
                                            "date": "2026-10-25"}, worker)
    s = _post(client, "field_submissions", {"date": "2026-10-26", "project_id": p["id"], "daily_report_id": dr["id"],
                                            "worksheets": [{"activity_id": ws["id"]}], "boreholes": [{"borehole_id": "BH-01"}]}, worker)
    assert s["number"].startswith("FS-") and s["sub_status"] == "draft" and s["item_count"] == 3 and s["recipients"] == "office"
    assert [w["text"] for w in s["warnings"]] == ["{code} is dated {date}, not the day of this package"]
    # Other field users do not see it; the office sees nothing to do until it is sent.
    assert client.get(f"/api/records/field_submissions/{s['id']}", headers=other).status_code == 404
    assert client.get("/api/erp/work/submissions/inbox", headers=manager).json() == []
    act = lambda h, action, note="", status=200: client.post(f"/api/erp/work/submissions/{s['id']}/act",  # noqa: E731
                                                            json={"action": action, "note": note}, headers=h)
    assert act(manager, "acknowledge").status_code == 409
    sent = act(worker, "submit").json()
    assert sent["sub_status"] == "submitted" and sent["_actions"] == [] and not sent["_can_edit"]
    # Locked once sent: no edits, no deletion.
    assert client.put(f"/api/records/field_submissions/{s['id']}", json={**{k: v for k, v in s.items() if not k.startswith("_")}, "note": "x"},
                      headers=worker).status_code == 409
    assert client.delete(f"/api/records/field_submissions/{s['id']}", headers=worker).status_code == 409
    # Without samples the laboratory is not a recipient.
    assert act(lab, "acknowledge").status_code in (404, 409)
    inbox = client.get("/api/erp/work/submissions/inbox", headers=manager).json()
    assert [i["state"] for i in inbox] == ["submitted"] and inbox[0]["items"] == 3
    assert client.get("/api/erp/work/summary", headers=manager).json()["submissions_waiting"] == 1
    assert act(worker, "acknowledge").status_code == 409
    assert act(manager, "acknowledge").json()["sub_status"] == "acknowledged"
    assert act(manager, "return").status_code == 409  # a note is needed
    back = act(manager, "return", "Log BH-01 belum ada deskripsi").json()
    assert back["sub_status"] == "returned"
    # Returned: the sender sees it waiting, can correct and send again.
    assert [i["note"] for i in client.get("/api/erp/work/submissions/inbox", headers=worker).json()] == ["Log BH-01 belum ada deskripsi"]
    fixed = _put(client, "field_submissions", back, {"samples_included": True, "sample_count": 4}, worker)
    assert fixed["recipients"] == "office_lab"
    assert act(worker, "submit").json()["resubmissions"] == 1
    # With samples the laboratory receives it too and can take it through.
    assert [i["samples"] for i in client.get("/api/erp/work/submissions/inbox", headers=lab).json()] == [True]
    assert act(lab, "process").json()["sub_status"] == "processing"
    final = act(manager, "done").json()
    assert final["sub_status"] == "done" and final["done_at"]
    assert [h["action"] for h in final["sub_history"]] == ["submit", "acknowledge", "return", "submit", "process", "done"]
    assert act(manager, "reopen", "Lampiran foto kurang").json()["sub_status"] == "processing"
    # The worksheet in the package cannot be deleted while the package refers to it.
    assert client.delete(f"/api/records/field_activities/{ws['id']}", headers=worker).status_code == 409


def test_submission_needs_content_and_day_records(client, admin_headers):
    worker = _h(client, "field1@example.com", "general")
    p = _project(client, admin_headers, status="ongoing")
    empty = _post(client, "field_submissions", {"date": "2026-10-26", "project_id": p["id"]}, worker)
    assert empty["warnings"][0]["text"] == "No daily report in this package"
    res = client.post(f"/api/erp/work/submissions/{empty['id']}/act", json={"action": "submit"}, headers=worker)
    assert res.status_code == 409
    # A draft can still be deleted by its sender.
    assert client.delete(f"/api/records/field_submissions/{empty['id']}", headers=worker).status_code == 200
    _post(client, "field_activities", {"code": "DR-1", "type": "general", "method": "daily_report", "project_id": p["id"], "date": "2026-10-26"}, worker)
    _post(client, "field_activities", {"code": "DR-0", "type": "general", "method": "daily_report", "project_id": p["id"], "date": "2026-10-26"},
          admin_headers)
    day = client.get(f"/api/erp/work/day-records?date=2026-10-26&project_id={p['id']}", headers=worker).json()
    assert [d["code"] for d in day["daily_reports"]] == ["DR-1"]  # field users pick from their own records
    assert client.get("/api/erp/work/day-records?date=26-10-2026", headers=worker).status_code == 422


# --------------------------------------------------------------------------- #
# Crew roster
# --------------------------------------------------------------------------- #

def test_deployment_figures():
    # 1 to 31 Oct 2026 at Rp 350,000 a day, as of 26 Oct: 26 man-days to date (1–26 Oct), 31 planned, cost 9,100,000.
    # Medical clearance until 5 Nov: 10 days left, within the 14-day warning. Induction 20 Oct 2025 + 12 months = 20 Oct 2026: expired.
    r = {"deploy_start": "2026-10-01", "deploy_end": "2026-10-31", "daily_rate": 350000, "medical_expiry": "2026-11-05",
         "induction_date": "2025-10-20", "emergency_phone": "0812"}
    f = erp_work.deployment_figures(r, TODAY, CFG)
    assert f["deployment_status"] == "on_site" and f["man_days"] == 26 and f["planned_man_days"] == 31
    assert f["cost_to_date"] == 9_100_000
    assert f["medical_state"] == "expiring" and f["induction_state"] == "expired" and f["compliance"] == "expired"
    assert f["induction_valid_until"] == "2026-10-20"
    assert [w["text"] for w in f["warnings"]] == ["Medical clearance expires on {date}", "Safety induction expired on {date}: repeat it before work"]
    # Planned (starts later): no man-days yet. Finished: counted to the end, documents no longer checked.
    assert erp_work.deployment_figures({**r, "deploy_start": "2026-11-01", "deploy_end": None}, TODAY, CFG)["man_days"] == 0
    done = erp_work.deployment_figures({**r, "deploy_start": "2026-09-01", "deploy_end": "2026-09-10"}, TODAY, CFG)
    assert done["deployment_status"] == "finished" and done["man_days"] == 10 and done["compliance"] == "ok" and not done["warnings"]
    # Medical ending before the deployment does.
    late = erp_work.deployment_figures({**r, "medical_expiry": "2026-12-15", "deploy_end": "2026-12-31", "induction_date": "2026-09-01"},
                                       TODAY, CFG)
    assert [w["text"] for w in late["warnings"]] == ["Medical clearance ends on {date}, before the deployment ends"]


def test_roster_daily_rate_visibility(client, admin_headers):
    worker = _h(client, "field1@example.com", "general")
    finance = _h(client, "fin@example.com", "finance")
    lab = _h(client, "lab1@example.com", "lab")
    p = _project(client, admin_headers, status="ongoing")
    row = {"project_id": p["id"], "person_name": "Pekerja Bor A", "position": "driller", "employer_type": "daily",
           "deploy_start": "2026-10-01", "deploy_end": "2026-10-10", "daily_rate": 250000, "medical_expiry": "2027-06-01",
           "induction_date": "2026-09-30", "emergency_phone": "0812"}
    r = _post(client, "crew_deployments", row, admin_headers)
    assert r["man_days"] == 10 and r["cost_to_date"] == 2_500_000 and r["deployment_status"] == "finished"
    assert client.post("/api/records/crew_deployments", json=row, headers=worker).status_code == 403
    assert client.post("/api/records/crew_deployments", json={**row, "deploy_end": "2026-09-01"}, headers=admin_headers).status_code == 422
    seen = client.get("/api/records/crew_deployments", headers=worker).json()[0]
    assert "daily_rate" not in seen and "cost_to_date" not in seen and seen["man_days"] == 10
    live = client.get(f"/api/erp/work/roster?project_id={p['id']}", headers=worker).json()
    assert "daily_rate" not in live["rows"][0] and "cost_to_date" not in live["rows"][0] and "cost_to_date" not in live["projects"][0]
    assert live["projects"][0]["man_days"] == 10 and live["totals"]["people"] == 1
    fin = client.get("/api/erp/work/roster", headers=finance).json()
    assert fin["rows"][0]["daily_rate"] == 250000 and fin["projects"][0]["cost_to_date"] == 2_500_000
    assert client.get("/api/erp/work/roster", headers=lab).status_code == 403


# --------------------------------------------------------------------------- #
# Laboratory work orders
# --------------------------------------------------------------------------- #

def test_order_state_hand_checked():
    tests = {
        "a" * 16: {"id": "a" * 16, "test_type": "moisture", "status": "done", "authorised": True},
        "b" * 16: {"id": "b" * 16, "test_type": "triaxial", "status": "testing"},
    }
    order = {"received": "2026-10-05", "tests": [{"lab_test_id": "a" * 16}, {"lab_test_id": "b" * 16}]}
    s = erp_work.order_state(order, tests, CFG, TODAY)
    # Slowest test: triaxial, 14 working days -> due Fri 23 Oct. Progress (1.0 + 0.5) / 2 = 75 %.
    assert s["sla_days"] == 14 and s["due_date"] == "2026-10-23" and s["progress_pct"] == 75 and s["status"] == "in_testing"
    # As of Mon 26 Oct it is one working day late.
    assert s["overdue"] and s["days_late"] == 1 and s["days_left"] == -1
    assert s["by_category"] == {"index": {"tests": 1, "done": 1, "authorised": 1}, "triaxial": {"tests": 1, "done": 0, "authorised": 0}}
    # Calendar days: 5 + 14 = 19 Oct.
    assert erp_work.order_state(order, tests, {**CFG, "lab_sla_basis": "calendar"}, TODAY)["due_date"] == "2026-10-19"
    tests["b" * 16].update(status="done")
    assert erp_work.order_state(order, tests, CFG, TODAY)["status"] == "awaiting_review"
    tests["b" * 16].update(authorised=True)
    assert erp_work.order_state(order, tests, CFG, TODAY)["status"] == "ready"
    # Reported Wed 28 Oct: turnaround 17 working days (6–9, 12–16, 19–23, 26–28 Oct), late.
    rep = erp_work.order_state({**order, "reported_on": "2026-10-28"}, tests, CFG, TODAY)
    assert rep["status"] == "reported" and rep["turnaround_days"] == 17 and rep["on_time"] == "no" and not rep["overdue"]
    # An agreed due date overrides the targets.
    assert erp_work.order_state({**order, "agreed_due": "2026-11-30"}, tests, CFG, TODAY)["due_date"] == "2026-11-30"


def test_lab_kpis():
    states = [
        {"status": "reported", "turnaround_days": 17, "on_time": "no", "reported_on": "2026-10-28", "overdue": False},
        {"status": "reported", "turnaround_days": 9, "on_time": "yes", "reported_on": "2026-09-16", "overdue": False},
        {"status": "reported", "turnaround_days": 40, "on_time": "no", "reported_on": "2024-01-10", "overdue": False},  # older than 12 months
        {"status": "awaiting_review", "overdue": True},
        {"status": "in_testing", "overdue": False},
        {"status": "cancelled", "overdue": False},
    ]
    k = erp_work.lab_kpis(states, TODAY)
    # (17 + 9) / 2 = 13.0 days; 1 of 2 on time = 50 %.
    assert k["average_turnaround_days"] == 13.0 and k["on_time_pct"] == 50.0 and k["reported"] == 2
    assert k["open"] == 2 and k["overdue"] == 1 and k["awaiting_review"] == 1 and k["in_testing"] == 1


def test_lab_work_order_from_instruction_follows_tests(client, admin_headers):
    tech = _h(client, "tech@example.com", "lab")
    head = _h(client, "head@example.com", "lab")
    worker = _h(client, "field1@example.com", "general")
    finance = _h(client, "fin@example.com", "finance")
    p = _project(client, admin_headers, status="ongoing")
    base = {"borehole_id": "BH-01", "sample_ref": "UDS-1", "depth_top": 2.0, "status": "requested", "received": "2026-10-05", "project_id": p["id"]}
    t1 = _post(client, "lab_tests", {**base, "test_type": "moisture"}, tech)
    t2 = _post(client, "lab_tests", {**base, "test_type": "consolidation"}, tech)
    board = client.get("/api/erp/work/lab/board", headers=tech).json()
    assert {u["id"] for u in board["unassigned"]} == {t1["id"], t2["id"]}
    res = client.post("/api/erp/work/lab/orders/from-tests", json={"test_ids": [t1["id"], t2["id"]], "technician": "tech@example.com"}, headers=tech)
    assert res.status_code == 201, res.text
    o = res.json()
    # Consolidation governs: 21 working days after Mon 5 Oct: 6–9 (4), 12–16 (9), 19–23 (14), 26–30 Oct (19), 2–3 Nov -> Tue 3 Nov.
    assert o["number"].startswith("LWO-") and o["source"] == "instruction" and o["due_date"] == "2026-11-03"
    assert o["status"] == "received" and o["progress_pct"] == 0 and o["client_id"] == p["client_id"]
    # Testing one test moves the order on; the stored record follows the test.
    _put(client, "lab_tests", t1, {"status": "testing"}, tech)
    o = client.get(f"/api/records/lab_work_orders/{o['id']}", headers=tech).json()
    assert o["status"] == "in_testing" and o["progress_pct"] == 25  # (0.5 testing + 0 requested) / 2
    t1 = _put(client, "lab_tests", client.get(f"/api/records/lab_tests/{t1['id']}", headers=tech).json(),
              {"status": "done", "tested": "2026-10-07"}, tech)
    t2 = _put(client, "lab_tests", t2, {"status": "done", "tested": "2026-10-20"}, tech)
    o = client.get(f"/api/records/lab_work_orders/{o['id']}", headers=tech).json()
    assert o["status"] == "awaiting_review" and o["progress_pct"] == 80
    board = client.get("/api/erp/work/lab/board", headers=tech).json()
    assert board["kpis"]["awaiting_review"] == 1 and board["unassigned"] == []
    assert {q["category"] for q in board["queue"]} == {"index", "consolidation"}
    assert all(i["stage"] == "review" and i["order"]["number"] == o["number"] for q in board["queue"] for i in q["items"])
    # Reporting before authorisation is flagged (refused when Operations settings require authorisation).
    early = _put(client, "lab_work_orders", o, {"reported_on": "2026-10-21"}, tech)
    assert early["status"] == "reported" and early["warnings"][0]["text"].startswith("Reported before every test")
    o = _put(client, "lab_work_orders", early, {"reported_on": ""}, tech)
    for t in (t1, t2):
        _put(client, "lab_tests", t, {"authorised": True}, head)
    o = client.get(f"/api/records/lab_work_orders/{o['id']}", headers=tech).json()
    assert o["status"] == "ready" and o["progress_pct"] == 100 and o["tests_authorised"] == 2
    # Reported Wed 28 Oct: 17 working days, on or before the due date of 3 Nov.
    o = _put(client, "lab_work_orders", o, {"reported_on": "2026-10-28", "report_ref": "LAB-001"}, tech)
    assert o["status"] == "reported" and o["turnaround_days"] == 17 and o["on_time"] == "yes" and o["warning_count"] == 0
    # A second order with the same test is flagged; mixing projects is refused.
    dup = _post(client, "lab_work_orders", {"received": "2026-10-06", "tests": [{"lab_test_id": t1["id"]}]}, tech)
    assert any(w["text"].startswith("{sample} {test} is also on work order") for w in dup["warnings"])
    p2 = _post(client, "projects", {"code": "WRK-2", "name": "Proyek Dua", "client_id": p["client_id"]}, admin_headers)
    t3 = _post(client, "lab_tests", {**base, "test_type": "atterberg", "project_id": p2["id"]}, tech)
    assert client.post("/api/erp/work/lab/orders/from-tests", json={"test_ids": [t2["id"], t3["id"]]}, headers=tech).status_code == 422
    # Field staff cannot open the board or create orders; finance reads the board but cannot create.
    assert client.get("/api/erp/work/lab/board", headers=worker).status_code == 403
    assert client.post("/api/erp/work/lab/orders/from-tests", json={"test_ids": [t3["id"]]}, headers=worker).status_code == 403
    assert client.get("/api/erp/work/lab/board", headers=finance).status_code == 200
    assert client.post("/api/erp/work/lab/orders/from-tests", json={"test_ids": [t3["id"]]}, headers=finance).status_code == 403


def test_overview_for_management(client, admin_headers):
    p = _project(client, admin_headers, status="ongoing")
    res = client.get("/api/erp/work/overview", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["tasks"]["open"] == 7 and data["tasks"]["projects"][0]["code"] == "WRK-1"
    assert data["lab"]["open"] == 0 and data["crew"]["people"] == 0 and data["submissions"]["waiting"] == 0
    worker = _h(client, "field1@example.com", "general")
    assert client.get("/api/erp/work/overview", headers=worker).status_code == 403
    assert p["status"] == "ongoing"
