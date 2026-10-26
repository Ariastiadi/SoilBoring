"""Operations ERP: equipment register, mobilisation, maintenance work orders, vendors, procurement
card and purchase orders, fixed asset depreciation (PMK 72/2023, PSAK 216) and performance cards.
Expected values are worked out by hand in the comments."""
from datetime import date

import pytest

from backend.app import erp_ops
from backend.app.main import app
from backend.app.routers import erp_ops as erp_ops_router

from .conftest import login_headers, make_user

# The router is mounted by main.py once the lead wires it in; until then the tests mount it.
if not any(getattr(r, "path", "") == "/api/erp/ops/overview" for r in app.routes):
    app.include_router(erp_ops_router.router)

TODAY = date(2026, 10, 26)


def _h(client, email, role):
    return login_headers(client, *make_user(email, role=role))


def _post(client, entity, data, headers, status=201):
    res = client.post(f"/api/records/{entity}", json=data, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _project(client, headers):
    c = _post(client, "clients", {"name": "Klien Ops", "type": "private"}, headers)
    return _post(client, "projects", {"code": "OPS-1", "name": "Proyek Ops", "client_id": c["id"], "status": "ongoing"}, headers)


# --------------------------------------------------------------------------- #
# Pure calculations
# --------------------------------------------------------------------------- #

def test_add_months_clamps_to_month_end():
    assert erp_ops.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert erp_ops.add_months(date(2025, 9, 1), 12) == date(2026, 9, 1)
    assert erp_ops.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_tax_straight_line_group2_full_month_convention():
    # Rp 400 jt, group 2 (8 years, 12.5%), acquired 15 Oct 2024: 400 jt / 96 months = 4,166,666.67 per month.
    # 2024: Oct–Dec = 3 months = 12.5 jt; 2025–2031: 50 jt a year; 2032: Jan–Sep = 9 months = 37.5 jt (life ends Sep 2032).
    rows = erp_ops.depreciation_rows(400_000_000, date(2024, 10, 15), 8, "straight_line", 12.5)
    assert [r["year"] for r in rows] == list(range(2024, 2033))
    assert rows[0]["months"] == 3 and rows[0]["dep"] == 12_500_000
    assert all(r["dep"] == 50_000_000 for r in rows[1:8])
    assert rows[-1]["months"] == 9 and rows[-1]["dep"] == 37_500_000 and rows[-1]["closing"] == 0
    # As of 26 Oct 2026: Oct 2024 .. Oct 2026 = 25 months x 4,166,666.67 = 104,166,667.
    assert erp_ops.accumulated_at(rows, date(2024, 10, 15), TODAY) == 104_166_667
    assert erp_ops.accumulated_at(rows, date(2024, 10, 15), date(2024, 9, 30)) == 0


def test_tax_declining_balance_group1_writes_off_rest_at_end_of_life():
    # Rp 100 jt, group 1 (4 years, 50%), acquired 1 Jul 2025 (48 months, ends Jun 2029).
    # 2025: 100 x 50% x 6/12 = 25 jt -> 75; 2026: 37.5 -> 37.5; 2027: 18.75 -> 18.75; 2028: 9.375 -> 9.375;
    # 2029 (6 months, life ends): the remaining 9.375 jt is depreciated at once.
    rows = erp_ops.depreciation_rows(100_000_000, date(2025, 7, 1), 4, "declining", 50)
    assert [(r["year"], r["months"], r["dep"]) for r in rows] == [
        (2025, 6, 25_000_000), (2026, 12, 37_500_000), (2027, 12, 18_750_000), (2028, 12, 9_375_000), (2029, 6, 9_375_000)]
    assert rows[-1]["closing"] == 0


def test_book_double_declining_stops_at_residual():
    # Rp 400 jt, 5 years, residual 40 jt, from 1 Jan 2025: rate 2/5 = 40%.
    # 2025: 160 -> 240; 2026: 96 -> 144; 2027: 57.6 -> 86.4; 2028: 34.56 -> 51.84; 2029: down to residual = 11.84 jt.
    rows = erp_ops.depreciation_rows(400_000_000, date(2025, 1, 1), 5, "declining", 40, residual=40_000_000)
    assert [r["dep"] for r in rows] == [160_000_000, 96_000_000, 57_600_000, 34_560_000, 11_840_000]
    assert rows[-1]["closing"] == 40_000_000


def test_kpi_achievement_and_rating():
    assert erp_ops.kpi_achievement(10, 12, "higher", 120) == 120  # 120% (at the cap)
    assert erp_ops.kpi_achievement(20, 15, "higher", 120) == 75
    assert erp_ops.kpi_achievement(4, 3, "lower", 200) == 125  # (2 - 3/4) x 100
    assert erp_ops.kpi_achievement(4, 9, "lower", 120) == 0  # (2 - 2.25) floored at 0
    assert erp_ops.kpi_achievement(0, 0, "lower", 120) == 100  # zero accidents
    assert erp_ops.kpi_achievement(0, 1, "lower", 120) == 0
    assert [erp_ops.rating_for(s) for s in (115, 114.99, 105, 90, 89.9, 70, 69.9)] == [
        "outstanding", "very_good", "very_good", "good", "needs_improvement", "needs_improvement", "unsatisfactory"]


# --------------------------------------------------------------------------- #
# Fixed asset card through the API
# --------------------------------------------------------------------------- #

def test_fixed_asset_disposal_gain_and_validation(client, admin_headers):
    # Rp 400 jt, group 2 straight line, acquired 15 Oct 2024, sold 10 Mar 2026 for Rp 350 jt.
    # Depreciation to end of March 2026 = 18 months x 4,166,666.67 = 75 jt; book value 325 jt; gain 25 jt.
    a = _post(client, "fixed_assets", {"code": "FA-001", "name": "Drill rig", "category": "drilling", "acquisition_date": "2024-10-15",
                                       "cost": 400_000_000, "tax_group": "g2", "tax_method": "straight_line", "book_method": "same_as_tax",
                                       "disposal_date": "2026-03-10", "disposal_type": "sale", "disposal_proceeds": 350_000_000}, admin_headers)
    assert a["asset_status"] == "disposed" and a["as_of"] == "2026-03-10"
    assert a["accumulated_tax"] == 75_000_000 and a["tax_value"] == 325_000_000
    assert a["book_value"] == 325_000_000 and a["gain_loss_book"] == 25_000_000 and a["gain_loss_tax"] == 25_000_000
    assert a["tax_life_years"] == 8 and a["tax_rate_pct"] == 12.5
    book = a["schedule"]["tables"][0]
    assert [r[0] for r in book["rows"]] == ["2024", "2025", "2026"] and book["rows"][2][3] == 12_500_000
    assert any("PMK 72 Tahun 2023" in n for n in a["schedule"]["notes"])
    # A building cannot use declining balance; codes are unique; residual not above cost.
    bad = {"code": "FA-002", "name": "Gedung", "category": "building_permanent", "acquisition_date": "2024-01-01", "cost": 1_000_000_000,
           "tax_group": "building_permanent", "tax_method": "declining", "book_method": "same_as_tax"}
    assert client.post("/api/records/fixed_assets", json=bad, headers=admin_headers).status_code == 422
    assert client.post("/api/records/fixed_assets", json={**bad, "tax_method": "straight_line", "code": "fa-001"}, headers=admin_headers).status_code == 409
    assert client.post("/api/records/fixed_assets", json={**bad, "tax_method": "straight_line", "residual_value": 2_000_000_000},
                       headers=admin_headers).status_code == 422
    # Live schedule as of a chosen date: 1 Jan 2025 -> Oct-Dec 2024 + Jan 2025 = 4 months = 16,666,667; not yet disposed.
    live = client.get(f"/api/erp/ops/assets/{a['id']}/schedule?as_of=2025-01-01", headers=admin_headers).json()
    values = {v["label"]: v["value"] for v in live["values"]}
    assert values["Accumulated depreciation (tax)"] == 16_666_667 and "Gain / loss on disposal (books)" not in values
    # Land is not depreciated.
    land = _post(client, "fixed_assets", {"code": "FA-003", "name": "Tanah", "category": "land", "acquisition_date": "2020-05-01",
                                          "cost": 900_000_000, "tax_group": "none", "tax_method": "straight_line", "book_method": "same_as_tax"},
                 admin_headers)
    assert land["asset_status"] == "not_depreciated" and land["book_value"] == 900_000_000


def test_fixed_assets_hidden_from_field_staff(client, admin_headers):
    staff = _h(client, "staff@example.com", "general")
    assert client.get("/api/records/fixed_assets", headers=staff).status_code == 403


# --------------------------------------------------------------------------- #
# Equipment, work orders, mobilisation
# --------------------------------------------------------------------------- #

def test_equipment_due_dates_from_card_and_work_orders(client, admin_headers):
    eq = _post(client, "equipment", {"code": "DR-01", "name": "Mesin bor", "category": "drill_rig", "status": "available",
                                     "calibration_months": 12, "last_calibration": "2025-09-01",
                                     "service_days": 90, "service_hours": 250, "last_service_date": "2026-08-01",
                                     "last_service_hours": 1000, "hour_meter": 1240}, admin_headers)
    # Calibration 1 Sep 2025 + 12 months = 1 Sep 2026; service 1 Aug + 90 days = 30 Oct 2026, or at 1000 + 250 = 1250 h.
    assert eq["next_calibration_due"] == "2026-09-01" and eq["next_service_due"] == "2026-10-30" and eq["next_service_hours"] == 1250
    assert client.post("/api/records/equipment", json={"code": "dr-01", "name": "Dup", "category": "pump", "status": "available"},
                       headers=admin_headers).status_code == 409
    board = {b["code"]: b for b in erp_ops.equipment_board(TODAY)}
    assert board["DR-01"]["calibration_status"] == "overdue"
    assert board["DR-01"]["service_status"] == "due_soon"  # 4 days and 10 h left, inside the 30 days / 50 h warning
    due = erp_ops.maintenance_due(TODAY)
    assert [(i["kind"], i["status"]) for i in due["items"]] == [("calibration", "overdue"), ("service", "due_soon")]
    assert due["summary"] == "Overdue = 1; Due soon = 1"

    # A completed preventive work order at 1255 h on 20 Oct resets the service: next 18 Jan 2027 or 1505 h.
    wo = _post(client, "work_orders", {"equipment_id": eq["id"], "type": "preventive", "status": "completed", "date": "2026-10-19",
                                       "start_date": "2026-10-19", "completed_date": "2026-10-20", "hour_meter": 1255,
                                       "description": "Servis 250 jam", "parts": [{"part": "Filter oli", "qty": 2, "unit_cost": 150_000}],
                                       "labour_cost": 300_000}, admin_headers)
    assert wo["number"] == "WO-2026-001" and wo["parts_cost"] == 300_000 and wo["total_cost"] == 600_000 and wo["downtime"] == 1
    # A completed calibration on 1 Oct 2026: next due 1 Oct 2027 on the work order and the board.
    cal = _post(client, "work_orders", {"equipment_id": eq["id"], "type": "calibration", "status": "completed", "date": "2026-10-01",
                                        "completed_date": "2026-10-01", "description": "Kalibrasi", "calibration_result": "pass",
                                        "certificate_no": "CAL-77", "downtime_days": 0}, admin_headers)
    assert cal["next_calibration_due"] == "2027-10-01" and cal["warning_count"] == 0 and cal["downtime"] == 0
    b = {x["code"]: x for x in erp_ops.equipment_board(TODAY)}["DR-01"]
    assert b["next_service_due"] == "2027-01-18" and b["next_service_hours"] == 1505 and b["hours_now"] == 1255
    assert b["service_status"] == "ok" and b["calibration_status"] == "ok" and b["next_calibration_due"] == "2027-10-01"
    # Completed without a date, and completion before start, are refused.
    base = {"equipment_id": eq["id"], "type": "corrective", "date": "2026-10-21", "description": "Bocor hidrolik"}
    assert client.post("/api/records/work_orders", json={**base, "status": "completed"}, headers=admin_headers).status_code == 422
    assert client.post("/api/records/work_orders", json={**base, "status": "completed", "start_date": "2026-10-22",
                                                         "completed_date": "2026-10-21"}, headers=admin_headers).status_code == 422
    # Above the approval limit (Rp 25 jt) without a procurement card: 2 x 10 jt + 6 jt = 26 jt -> warning.
    big = _post(client, "work_orders", {**base, "status": "open", "parts": [{"part": "Pompa hidrolik", "qty": 2, "unit_cost": 10_000_000}],
                                        "labour_cost": 6_000_000}, admin_headers)
    assert big["total_cost"] == 26_000_000 and big["warning_count"] == 1
    assert big["warnings"][0]["vars"]["limit"] == 25_000_000 and big["warnings"][0]["money"] == ["limit"]


def test_mobilisation_status_conflicts_and_costs(client, admin_headers):
    p = _project(client, admin_headers)
    rig = _post(client, "equipment", {"code": "DR-02", "name": "Mesin bor 2", "category": "drill_rig", "status": "available",
                                      "location": "Gudang"}, admin_headers)
    cpt = _post(client, "equipment", {"code": "SD-01", "name": "Sondir 2,5 t", "category": "cpt_rig", "status": "broken"}, admin_headers)
    old = _post(client, "equipment", {"code": "PM-09", "name": "Pompa lama", "category": "pump", "status": "disposed"}, admin_headers)
    m = _post(client, "mobilisations", {"date": "2026-10-01", "project_id": p["id"], "status": "on_site", "to_location": "Site A",
                                        "planned_mob_date": "2026-10-05", "actual_mob_date": "2026-10-06", "planned_demob_date": "2026-11-04",
                                        "equipment": [{"equipment_id": rig["id"]}, {"equipment_id": cpt["id"]}],
                                        "crew": [{"name": "Driller 1", "role": "driller"}],
                                        "mob_cost": 7_500_000, "demob_cost": 7_000_000, "other_cost": 1_250_000}, admin_headers)
    # Planned 5 Oct to 4 Nov = 31 days; total cost 7.5 + 7 + 1.25 = 15.75 jt; the broken CPT rig is warned about.
    assert m["number"] == "MOB-2026-001" and m["total_cost"] == 15_750_000 and m["planned_days"] == 31 and m["equipment_count"] == 2
    assert m["warning_count"] == 1
    board = {b["code"]: b for b in erp_ops.equipment_board(TODAY)}
    assert board["DR-02"]["status"] == "mobilised" and board["DR-02"]["manual_status"] == "available"
    assert board["DR-02"]["location"] == "Site A" and board["DR-02"]["mobilisation"]["number"] == "MOB-2026-001"
    assert board["SD-01"]["status"] == "broken" and board["SD-01"]["note"] == "Listed on an active mobilisation"
    # The same rig booked on an overlapping planned mobilisation is warned about; disposed equipment is refused.
    m2 = _post(client, "mobilisations", {"date": "2026-10-20", "project_id": p["id"], "status": "planned", "to_location": "Site B",
                                         "planned_mob_date": "2026-11-01", "planned_demob_date": "2026-11-20",
                                         "equipment": [{"equipment_id": rig["id"]}]}, admin_headers)
    assert m2["warning_count"] == 1 and m2["warnings"][0]["vars"]["number"] == "MOB-2026-001"
    assert client.post("/api/records/mobilisations", json={"date": "2026-10-20", "project_id": p["id"], "status": "planned", "to_location": "X",
                                                           "equipment": [{"equipment_id": old["id"]}]}, headers=admin_headers).status_code == 422
    assert client.post("/api/records/mobilisations", json={"date": "2026-10-20", "project_id": p["id"], "status": "planned", "to_location": "X",
                                                           "planned_mob_date": "2026-11-02", "planned_demob_date": "2026-11-01"},
                       headers=admin_headers).status_code == 422
    # Back at base: no longer mobilised.
    put = client.put(f"/api/records/mobilisations/{m['id']}", json={**{k: m[k] for k in ("date", "project_id", "to_location", "planned_mob_date",
                                                                                       "actual_mob_date", "planned_demob_date", "equipment")},
                                                                   "status": "returned", "actual_demob_date": "2026-11-03"}, headers=admin_headers)
    assert put.status_code == 200 and put.json()["actual_days"] == 29  # 6 Oct to 3 Nov
    assert {b["code"]: b for b in erp_ops.equipment_board(TODAY)}["DR-02"]["status"] == "available"
    # Mobilisation costs are private: field staff do not see them.
    staff = _h(client, "field@example.com", "general")
    row = client.get(f"/api/records/mobilisations/{m['id']}", headers=staff).json()
    assert "total_cost" not in row and "mob_cost" not in row


def test_vendor_names_unique_and_bank_private(client, admin_headers):
    _post(client, "vendors", {"name": "CV Suku Cadang", "category": "parts", "npwp": "01.234.567.8-901.000", "bank_account": "123"}, admin_headers)
    assert client.post("/api/records/vendors", json={"name": "cv suku cadang", "category": "parts"}, headers=admin_headers).status_code == 409
    staff = _h(client, "field2@example.com", "general")
    row = client.get("/api/records/vendors", headers=staff).json()[0]
    assert row["name"] == "CV Suku Cadang" and "npwp" not in row and "bank_account" not in row


# --------------------------------------------------------------------------- #
# Procurement card and purchase orders
# --------------------------------------------------------------------------- #

def test_procurement_quote_rules_budget_and_numbering(client, admin_headers):
    v1 = _post(client, "vendors", {"name": "Vendor A", "category": "parts"}, admin_headers)
    v2 = _post(client, "vendors", {"name": "Vendor B", "category": "parts"}, admin_headers)
    # Estimated 2 x 30 jt = 60 jt -> three quotations needed (from 50 jt). Two received; the chosen one (58 jt)
    # is not the lowest (55 jt) and has no reason; 58 jt is 1 jt above the 57 jt budget.
    pr = _post(client, "procurements", {"date": "2026-10-10", "title": "Pompa lumpur", "cost_centre": "workshop", "budget": 57_000_000,
                                        "items": [{"description": "Pompa lumpur 3 inch", "qty": 2, "est_price": 30_000_000}],
                                        "quotations": [{"vendor_id": v1["id"], "amount": 58_000_000, "chosen": True},
                                                       {"vendor_id": v2["id"], "amount": 55_000_000}]}, admin_headers)
    assert pr["number"] == "PR-2026-001" and pr["wf_status"] == "draft"
    assert pr["est_total"] == 60_000_000 and pr["quote_count"] == 2 and pr["required_quotes"] == 3
    assert pr["lowest_amount"] == 55_000_000 and pr["chosen_vendor"] == "Vendor A" and pr["approved_amount"] == 58_000_000
    texts = [w["text"] for w in pr["warnings"]]
    assert len(texts) == 3 and any(t.startswith("{needed} quotations") for t in texts)
    over = next(w for w in pr["warnings"] if w["text"].startswith("Above the budget"))
    assert over["vars"]["over"] == 1_000_000
    # With the reasons given the quotation warnings go; two chosen quotations are refused.
    fixed = client.put(f"/api/records/procurements/{pr['id']}", json={**{k: pr[k] for k in ("date", "title", "cost_centre", "items", "quotations")},
                                                                     "budget": 60_000_000, "selection_reason": "Garansi 2 tahun",
                                                                     "exception_reason": "Hanya dua distributor resmi"}, headers=admin_headers).json()
    assert fixed["warning_count"] == 0
    two = [{"vendor_id": v1["id"], "amount": 1, "chosen": True}, {"vendor_id": v2["id"], "amount": 2, "chosen": True}]
    assert client.post("/api/records/procurements", json={"date": "2026-10-10", "title": "X", "cost_centre": "office", "quotations": two},
                       headers=admin_headers).status_code == 422
    # Below 10 jt one quotation is enough.
    small = _post(client, "procurements", {"date": "2026-10-11", "title": "ATK", "cost_centre": "office",
                                           "items": [{"description": "Kertas", "qty": 10, "est_price": 50_000}],
                                           "quotations": [{"vendor_name": "Toko", "amount": 500_000, "chosen": True}]}, admin_headers)
    # (records.save takes the number before the checks, so the refused card above used PR-2026-002.)
    assert small["number"].startswith("PR-2026-") and small["required_quotes"] == 1 and small["warning_count"] == 0


def test_procurement_flow_requester_to_paid(client, admin_headers):
    requester = _h(client, "req@example.com", "general")
    other = _h(client, "other@example.com", "general")
    manager = _h(client, "mgr@example.com", "manager")
    finance = _h(client, "fin@example.com", "finance")
    v1 = _post(client, "vendors", {"name": "Vendor C", "category": "parts"}, admin_headers)
    v2 = _post(client, "vendors", {"name": "Vendor D", "category": "parts"}, admin_headers)
    # 20 jt estimate -> two quotations needed; chosen 22.2 jt is the lowest.
    pr = _post(client, "procurements", {"date": "2026-10-12", "title": "Batang bor", "requester": "req@example.com", "cost_centre": "field_ops",
                                        "items": [{"description": "Batang bor NW 3 m", "qty": 10, "est_price": 2_000_000}],
                                        "quotations": [{"vendor_id": v1["id"], "amount": 22_200_000, "chosen": True},
                                                       {"vendor_id": v2["id"], "amount": 23_000_000}]}, requester)
    assert pr["warning_count"] == 0 and pr["approved_amount"] == 22_200_000
    # Staff see only their own procurement cards.
    assert client.get("/api/records/procurements", headers=other).json() == []
    assert client.get(f"/api/records/procurements/{pr['id']}", headers=other).status_code == 404
    url = f"/api/records/procurements/{pr['id']}/workflow"
    po_body = {"procurement_id": pr["id"], "vendor_id": v1["id"], "date": "2026-10-15", "status": "issued", "tax_pct": 11,
               "items": [{"description": "Batang bor NW 3 m", "qty": 10, "unit_price": 1_000_000},
                         {"description": "Kopling", "qty": 5, "unit_price": 2_000_000}]}
    # Not approved yet: a purchase order cannot be issued (a draft can).
    assert client.post("/api/records/purchase_orders", json=po_body, headers=finance).status_code == 422
    assert client.post(url, json={"action": "submit"}, headers=requester).json()["wf_status"] == "submitted"
    assert client.post(url, json={"action": "review"}, headers=manager).json()["wf_status"] == "reviewed"
    assert client.post(url, json={"action": "approve"}, headers=admin_headers).json()["wf_status"] == "approved"
    stage = {s["id"]: s for s in client.get("/api/erp/ops/procurement-status", headers=requester).json()}[pr["id"]]
    assert stage["stage"] == "approved" and stage["ordered"] is None  # requester does not see PO amounts
    # PO: 10 x 1 jt + 5 x 2 jt = 20 jt + VAT 11% 2.2 jt = 22.2 jt; receipts 10 + 2 of 15 units = 80%.
    po = _post(client, "purchase_orders", {**po_body, "receipts": [{"date": "2026-10-20", "line": 1, "qty": 10},
                                                                   {"date": "2026-10-20", "line": 2, "qty": 2}]}, finance)
    assert po["number"].startswith("PO-2026-") and po["subtotal"] == 20_000_000 and po["tax"] == 2_200_000 and po["total"] == 22_200_000
    assert po["received_pct"] == 80 and po["progress"] == "partly_received" and po["warning_count"] == 0
    st = {s["id"]: s for s in client.get("/api/erp/ops/procurement-status", headers=finance).json()}[pr["id"]]
    assert st["stage"] == "partly_received" and st["ordered"] == 22_200_000
    # A receipt for an item number that does not exist is refused.
    assert client.put(f"/api/records/purchase_orders/{po['id']}", json={**po_body, "receipts": [{"date": "2026-10-21", "line": 3, "qty": 1}]},
                      headers=finance).status_code == 422
    # Rest received, invoice matching the PO, paid.
    done = client.put(f"/api/records/purchase_orders/{po['id']}", json={**po_body, "receipts": po["receipts"] + [{"date": "2026-10-22", "line": 2, "qty": 3}],
                                                                       "invoice_no": "INV-V-9", "invoice_date": "2026-10-23",
                                                                       "invoice_amount": 22_200_000, "paid_date": "2026-10-25"}, headers=finance).json()
    assert done["received_pct"] == 100 and done["progress"] == "paid" and done["warning_count"] == 0
    # A second PO above the approved amount and from another vendor is warned about.
    extra = _post(client, "purchase_orders", {**po_body, "vendor_id": v2["id"], "status": "draft",
                                              "items": [{"description": "Tambahan", "qty": 1, "unit_price": 1_000_000}]}, finance)
    texts = [w["text"] for w in extra["warnings"]]
    assert "The vendor differs from the chosen quotation" in texts
    assert any(t.startswith("Purchase orders exceed the approved amount") for t in texts)
    # Drafts do not move the stage: still paid.
    st = {s["id"]: s for s in client.get("/api/erp/ops/procurement-status", headers=finance).json()}[pr["id"]]
    assert st["stage"] == "paid" and st["paid"] == 22_200_000


# --------------------------------------------------------------------------- #
# Performance cards
# --------------------------------------------------------------------------- #

KPIS = [
    {"perspective": "financial", "kpi": "Pendapatan proyek", "unit": "Rp miliar", "target": 10, "weight": 40, "polarity": "higher", "actual": 12},
    {"perspective": "customer", "kpi": "Keluhan klien", "unit": "kali", "target": 4, "weight": 30, "polarity": "lower", "actual": 3},
    {"perspective": "internal", "kpi": "Laporan tepat waktu", "unit": "laporan", "target": 20, "weight": 30, "polarity": "higher", "actual": 15},
]
COMPS = [{"competency": "Kerja sama", "weight": 50, "score": "3"}, {"competency": "K3", "weight": 50, "score": "4"}]


def test_performance_card_scores_validation_and_privacy(client, admin_headers):
    staff = _h(client, "engineer@example.com", "general")
    colleague = _h(client, "colleague@example.com", "general")
    manager = _h(client, "lead@example.com", "manager")
    body = {"employee": "engineer@example.com", "employee_name": "Staf Teknik", "position": "Site engineer", "period_type": "annual",
            "period_start": "2026-01-01", "period_end": "2026-12-31", "kpis": KPIS, "competencies": COMPS, "kpi_share_pct": 70}
    card = _post(client, "performance_cards", body, staff)
    # KPIs: 120% (cap) x 40 = 48; (2 - 3/4) = 125% -> cap 120% x 30 = 36; 75% x 30 = 22.5 -> KPI score 106.5.
    # Behaviour: 3 -> 100% x 50 = 50; 4 -> 110% x 50 = 55 -> 105. Final 106.5 x 0.7 + 105 x 0.3 = 106.05 -> Very good.
    assert card["kpi_weight_total"] == 100 and card["kpi_score"] == 106.5 and card["competency_score"] == 105
    assert card["final_score"] == 106.05 and card["rating"] == "very_good" and card["title"] == "Staf Teknik – 2026"
    persp = card["scorecard"]["tables"][1]["rows"]
    assert persp == [["Financial", 40, 48], ["Customer", 30, 36], ["Internal process", 30, 22.5]]
    # Weights must add up to 100%.
    bad = {**body, "kpis": [{**KPIS[0], "weight": 50}, KPIS[1]]}
    assert client.post("/api/records/performance_cards", json=bad, headers=staff).status_code == 422
    # Without every actual there is no final score yet.
    plan = _post(client, "performance_cards", {**body, "period_start": "2027-01-01", "period_end": "2027-12-31",
                                               "kpis": [{**k, "actual": None} for k in KPIS]}, staff)
    assert plan["final_score"] is None and plan["rating"] == "" and plan["kpi_score"] is None and plan["competency_score"] == 105
    # Staff see only their own cards; the manager sees all of them.
    assert client.get("/api/records/performance_cards", headers=colleague).json() == []
    assert client.get(f"/api/records/performance_cards/{card['id']}", headers=colleague).status_code == 404
    assert len(client.get("/api/records/performance_cards", headers=manager).json()) == 2
    # Employee drafts -> superior reviews -> approver approves.
    url = f"/api/records/performance_cards/{card['id']}/workflow"
    assert client.post(url, json={"action": "submit"}, headers=staff).json()["wf_status"] == "submitted"
    assert client.post(url, json={"action": "review"}, headers=colleague).status_code == 404
    assert client.post(url, json={"action": "review"}, headers=manager).json()["wf_status"] == "reviewed"
    assert client.post(url, json={"action": "approve"}, headers=admin_headers).json()["wf_status"] == "approved"


# --------------------------------------------------------------------------- #
# Overview for the management dashboard
# --------------------------------------------------------------------------- #

def test_ops_overview_shape_and_roles(client, admin_headers):
    staff = _h(client, "viewer@example.com", "general")
    assert client.get("/api/erp/ops/overview", headers=staff).status_code == 403
    _post(client, "equipment", {"code": "TS-01", "name": "Total station", "category": "survey", "status": "available",
                                "calibration_months": 12}, admin_headers)
    _post(client, "equipment", {"code": "PM-01", "name": "Pompa", "category": "pump", "status": "broken"}, admin_headers)
    _post(client, "fixed_assets", {"code": "FA-010", "name": "Laptop", "category": "office_it", "acquisition_date": "2025-01-01",
                                   "cost": 24_000_000, "tax_group": "g1", "tax_method": "straight_line", "book_method": "same_as_tax"}, admin_headers)
    res = client.get("/api/erp/ops/overview", headers=admin_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert set(data) == {"as_of", "equipment", "maintenance", "procurement", "assets", "performance"}
    assert data["equipment"]["total"] == 2 and data["equipment"]["by_status"] == {"available": 1, "broken": 1}
    assert data["maintenance"]["calibration_overdue"] == 1  # never calibrated
    assert data["assets"]["count"] == 1 and data["assets"]["cost"] == 24_000_000
    # Laptop, group 1 (4 years): 0.5 jt a month; accumulated = months since Jan 2025 through this month.
    today = date.today()
    months = min(48, (today.year - 2025) * 12 + today.month)
    assert data["assets"]["accumulated_book"] == 500_000 * months
    assert data["procurement"]["in_progress"] == 0 and data["performance"]["cards"] == 0
    # Finance gets the overview too, but sees only its own performance cards.
    fin = _h(client, "fin2@example.com", "finance")
    assert client.get("/api/erp/ops/overview", headers=fin).json()["performance"]["cards"] == 0


@pytest.mark.parametrize("value,expected", [(9_999_999, 1), (10_000_000, 2), (49_999_999, 2), (50_000_000, 3)])
def test_required_quotes_thresholds(value, expected):
    assert erp_ops.required_quotes(value, erp_ops.DEFAULT_SETTINGS) == expected
