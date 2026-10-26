"""Commercial ERP (blueprint A.1): difficulty index, PBD, conversion to client rates, client
decision, weekly work plan, bank guarantees / SKBDN, receivables, client card and overview.
Every expected figure below is worked out by hand in the comments."""
import pytest

from backend.app import erp_commercial as calc
from backend.app.main import app
from backend.app.routers import erp_commercial as erp_router

from .conftest import login_headers, make_user

# The lead registers the router in main.py; until then the tests add it themselves.
if not any(getattr(r, "path", "").startswith("/api/erp/commercial") for r in app.routes):
    app.include_router(erp_router.router)


@pytest.fixture
def people(client, admin_headers):
    mgr = login_headers(client, *make_user("pm@example.com", role="manager"))
    mgr2 = login_headers(client, *make_user("pm2@example.com", role="manager"))
    fin = login_headers(client, *make_user("fin@example.com", role="finance"))
    gen = login_headers(client, *make_user("field@example.com", role="general"))
    return {"admin": admin_headers, "mgr": mgr, "mgr2": mgr2, "fin": fin, "gen": gen}


def _post(client, headers, entity, data, status=201):
    res = client.post(f"/api/records/{entity}", json=data, headers=headers)
    assert res.status_code == status, res.text
    return res.json()


def _base(client, h):
    c = _post(client, h, "clients", {"name": "Klien Uji", "type": "private", "pricing_tier": "client"})
    p = _post(client, h, "projects", {"code": "P-1", "name": "Proyek Uji", "client_id": c["id"], "status": "tender",
                                      "province": "JT", "location": "Semarang", "services": ["geotechnical", "laboratory"],
                                      "start_date": "2025-02-01"})
    rate = _post(client, h, "rates", {"code": "DRL-30", "description": "Drilling 30 m", "unit": "m", "line": "geotechnical",
                                      "price": 750000, "internal_price": 600000, "min_price": 500000})
    return c, p, rate


def _scores(zone_score_ignored=5, score=3):
    # Every factor scored 3; the zone row says 5 but the zone (C → index 1) overrides it.
    return [{"key": f["key"], "factor": f["factor"], "score": zone_score_ignored if f["key"] == "zone" else score}
            for f in calc.DEFAULT_FACTORS]


def _pbd_data(p, rate, **extra):
    data = {
        "date": "2026-10-01", "project_id": p["id"], "scope": "partial", "services": ["geotechnical"], "duration_weeks": 6,
        "difficulty": _scores(), "margin_pct": 30, "tax_pct": 11, "rounding": "1000", "conversion": "spread",
        "costs": [
            {"section": "work", "rate_id": rate["id"], "description": "Drilling 30 m", "unit": "m", "qty": 60, "unit_cost": 400000},
            {"section": "accommodation", "description": "Crew accommodation", "unit": "person-day", "qty": 5, "days": 20, "unit_cost": 150000},
            {"section": "mobilisation", "description": "Rig mobilisation", "unit": "ls", "qty": 1, "unit_cost": 6000000},
            {"section": "demobilisation", "description": "Rig demobilisation", "unit": "ls", "qty": 1, "unit_cost": 5000000},
        ],
    }
    data.update(extra)
    return data


# --------------------------------------------------------------------------- #
# A.1.3 difficulty index
# --------------------------------------------------------------------------- #

def test_difficulty_index_defaults_and_zone():
    assert len(calc.DEFAULT_FACTORS) == 16
    # 15 factors × 3 + zone C (index 1) = 46; 46 / 16 = 2.875 → index 3 → 11 %.
    out = calc.difficulty(_scores(), calc.DEFAULT_FACTORS, "C")
    assert out["score"] == 2.88 and out["index"] == 3 and out["scored"] == 16
    assert calc.premium_table(None)[out["index"]] == 11.0
    # Half rounds up: 8 factors at 2 and 8 at 3 → 2.5 → index 3.
    rows = [{"key": f["key"], "score": 2 if i < 8 else 3} for i, f in enumerate(calc.DEFAULT_FACTORS)]
    assert calc.difficulty(rows, calc.DEFAULT_FACTORS, "")["index"] == 3
    # Weights from the company settings: zone weight 3, everything else 1 → (3×5 + 15×1) / 18 = 1.667 → 2.
    settings = {"difficulty_factors": [{"key": f["key"], "factor": f["factor"], "weight": 3 if f["key"] == "zone" else 1}
                                       for f in calc.DEFAULT_FACTORS],
                "risk_premium_table": [{"index": 2, "premium_pct": 9}]}
    rows = [{"key": f["key"], "score": 1} for f in calc.DEFAULT_FACTORS]
    out = calc.difficulty(rows, calc.effective_factors(settings), "N")
    assert out["score"] == 1.67 and out["index"] == 2
    assert calc.premium_table(settings) == {1: 5.0, 2: 9.0, 3: 11.0, 4: 14.0, 5: 17.0}
    assert calc.difficulty([], calc.DEFAULT_FACTORS, "")["index"] is None


def test_zone_table_matches_blueprint():
    assert [(z[0], z[3]) for z in calc.ZONES] == [("A", 1), ("B", 1), ("C", 1), ("D", 2), ("E", 2), ("F", 2), ("G", 3), ("H", 3),
                                                   ("I", 4), ("J", 4), ("K", 4), ("L", 5), ("M", 5), ("N", 5)]
    assert len(calc.PROVINCES) == 38 and set(calc.PROVINCE_ZONE) == {code for code, _ in calc.PROVINCES}
    assert calc.PROVINCE_ZONE["JK"] == "B" and calc.PROVINCE_ZONE["KR"] == "H" and calc.PROVINCE_ZONE["PS"] == "N"


# --------------------------------------------------------------------------- #
# A.1.1 / A.1.4 PBD and A.1.5 conversion to client rates
# --------------------------------------------------------------------------- #

def test_pbd_calculation(client, people):
    h = people["mgr"]
    c, p, rate = _base(client, h)
    assert p["zone"] == "C"
    pbd = _post(client, h, "pbd", _pbd_data(p, rate))
    assert pbd["number"].startswith("PBD-2026-") and pbd["wf_status"] == "draft"
    assert pbd["client_id"] == c["id"] and pbd["province"] == "JT" and pbd["zone"] == "C" and pbd["location"] == "Semarang"
    assert pbd["difficulty_index"] == 3 and pbd["risk_premium_pct"] == 11
    # ABP = 60 × 400,000 + 5 × 20 × 150,000 + 6,000,000 + 5,000,000 = 24 + 15 + 6 + 5 M = 50,000,000
    assert pbd["abp"] == 50_000_000
    assert pbd["risk_amount"] == 5_500_000          # 11 % of the ABP
    assert pbd["margin_amount"] == 15_000_000       # 30 % of the ABP
    assert pbd["bid_price"] == 70_500_000           # 50 + 5.5 + 15 M
    assert pbd["bid_with_vat"] == 78_255_000        # + 11 % VAT 7,755,000
    # Minimum: drilling at its minimum 60 × 500,000 = 30 M, other lines at cost 26 M.
    assert pbd["min_client_price"] == 56_000_000
    assert pbd["price_list_value"] == 45_000_000    # 60 × 750,000
    assert pbd["cost_ratio_pct"] == 70.92            # 50 / 70.5
    assert pbd["approval_level"] == "Approver 1"     # below 2 bn
    assert not [x for x in pbd["checks"] if x["level"] in ("error", "warn")]
    assert pbd["result"]["summary"].startswith("Difficulty index = 3; Risk premium = 11 %")
    build = {row[0]: row[2] for row in pbd["result"]["tables"][0]["rows"]}
    assert build["Bid price (excl. VAT)"] == 70_500_000 and build["Rounding"] == 0

    # The committee may set the risk premium itself; a thin margin breaks the cost ratio limit.
    pbd2 = _post(client, h, "pbd", _pbd_data(p, rate, risk_pct_override=5, margin_pct=10, rounding="1000000"))
    # 50 M + 2.5 M + 5 M = 57.5 M → rounded up to 58 M; ratio 50 / 58 = 86.21 % > 75 %.
    assert pbd2["bid_price"] == 58_000_000 and pbd2["cost_ratio_pct"] == 86.21
    texts = [x["text"] for x in pbd2["checks"]]
    assert any("above the company maximum" in t for t in texts) and any("set by the committee" in t for t in texts)
    # Below the minimum client price: margin 0 and premium 0 → 50 M < 56 M.
    pbd3 = _post(client, h, "pbd", _pbd_data(p, rate, risk_pct_override=0, margin_pct=0))
    assert any(x["level"] == "error" for x in pbd3["checks"])


def test_pbd_unit_cost_from_rate_buildup(client, people):
    h = people["mgr"]
    _, p, _ = _base(client, h)
    # HPJ = 800,000 / 8 h × 0.5 h/unit = 50,000 per test
    spt = _post(client, h, "rates", {"code": "SPT", "description": "SPT", "unit": "test", "price": 120000,
                                     "buildup": [{"section": "labour", "description": "Crew", "qty": 1, "unit_cost": 800000,
                                                  "life_hours": 8, "coef": 0.5}]})
    assert spt["cost_unit"] == 50000
    pbd = _post(client, h, "pbd", {"date": "2026-10-02", "project_id": p["id"], "costs": [
        {"section": "work", "rate_id": spt["id"], "description": "SPT", "qty": 10},
        {"section": "other", "description": "Unknown cost", "qty": 1}]})
    assert pbd["costs"][0]["unit_cost"] == 50000 and pbd["abp"] == 500000
    assert pbd["margin_pct"] == 30  # company default
    assert any("No unit cost for" in x["text"] and "Unknown cost" in x["vars"]["items"] for x in pbd["checks"])
    assert any("Score the difficulty factors" in x["text"] for x in pbd["checks"])


def _approve(client, people, entity, record_id):
    url = f"/api/records/{entity}/{record_id}/workflow"
    assert client.post(url, json={"action": "submit"}, headers=people["mgr"]).json()["wf_status"] == "submitted"
    assert client.post(url, json={"action": "review"}, headers=people["mgr2"]).json()["wf_status"] == "reviewed"
    res = client.post(url, json={"action": "approve"}, headers=people["admin"])
    assert res.json()["wf_status"] == "approved", res.text


def test_pbd_approval_and_quotation(client, people):
    h = people["mgr"]
    _, p, rate = _base(client, h)
    pbd = _post(client, h, "pbd", _pbd_data(p, rate))
    url = f"/api/erp/commercial/pbd/{pbd['id']}/quotation"
    assert client.post(url, json={}, headers=h).status_code == 409  # not approved yet
    _approve(client, people, "pbd", pbd["id"])
    assert client.post(url, json={}, headers=people["fin"]).status_code == 403  # finance cannot write quotations
    res = client.post(url, json={"date": "2026-10-20"}, headers=h)
    assert res.status_code == 201, res.text
    q = res.json()
    assert q["pbd_id"] == pbd["id"] and q["project_id"] == p["id"] and q["mob_demob"] == "included"
    assert q["valid_until"] == "2026-11-19" and q["status"] == "draft"
    # k = 1 + 11 % + 30 % = 1.41. Accommodation (15 M) spread over the drilling (24 M): loading 1.625.
    # Drilling 400,000 × 1.625 × 1.41 = 916,500 → 917,000; mob 6 M × 1.41 = 8,460,000; demob 7,050,000.
    prices = [(i["description"], i["qty"], i["unit_price"]) for i in q["items"]]
    assert prices == [("Drilling 30 m", 60, 917000), ("Rig mobilisation", 1, 8460000), ("Rig demobilisation", 1, 7050000)]
    assert q["subtotal"] == 70_530_000 and q["tax"] == 7_758_300 and q["total"] == 78_288_300
    assert q["price_check"] == ""
    # The approved PBD is locked, and it cannot be deleted while the quotation points at it.
    assert client.delete(f"/api/records/pbd/{pbd['id']}", headers=people["admin"]).status_code == 409


def test_conversion_separate_and_minimum_price():
    rates = {"r1": {"id": "r1", "description": "Drilling", "unit": "m", "min_price": 600000}}
    pbd = {"id": "x", "number": "PBD-1", "project_id": "p", "risk_premium_pct": 11, "margin_pct": 30, "tax_pct": 11,
           "conversion": "separate", "costs": [
               {"section": "work", "rate_id": "r1", "description": "Drilling", "qty": 60, "unit_cost": 400000},
               {"section": "accommodation", "description": "Accommodation", "qty": 5, "days": 20, "unit_cost": 150000}]}
    q = calc.quotation_from_pbd(pbd, rates, {"pricing_tier": "internal"}, "2026-10-01")
    # Drilling 400,000 × 1.41 = 564,000, raised to the minimum 600,000; accommodation 211,500 → 212,000 × 100 person-days.
    assert [(i["qty"], i["unit_price"]) for i in q["items"]] == [(60, 600000), (100, 212000)]
    assert q["price_tier"] == "internal" and q["mob_demob"] == "excluded"
    with pytest.raises(calc.CommercialError):
        calc.quotation_from_pbd({**pbd, "costs": [{"section": "other", "description": "x", "qty": 1}]}, rates, None, "2026-10-01")


# --------------------------------------------------------------------------- #
# A.1.2 client decision
# --------------------------------------------------------------------------- #

def test_client_decision(client, people):
    h = people["mgr"]
    c, p, rate = _base(client, h)
    pbd = _post(client, h, "pbd", _pbd_data(p, rate))
    terms = [{"name": "Down payment", "percent": 30}, {"name": "Field work", "percent": 30}, {"name": "Final report", "percent": 40}]
    low = client.post("/api/records/client_decisions", json={"date": "2026-10-05", "pbd_id": pbd["id"], "decided_price": 50_000_000}, headers=h)
    assert low.status_code == 422 and "minimum client price" in low.json()["detail"]
    cd = _post(client, h, "client_decisions", {"date": "2026-10-05", "pbd_id": pbd["id"], "decided_price": 72_000_000,
                                               "price_max": 71_000_000, "payment_terms": terms, "procurement": "tender"})
    assert cd["project_id"] == p["id"] and cd["client_id"] == c["id"] and cd["number"].startswith("CD-2026-")
    assert cd["proposed_price"] == 70_500_000 and cd["price_min"] == 56_000_000 and cd["difficulty_index"] == 3
    assert cd["risk_premium_pct"] == 11 and cd["zone"] == "C" and cd["location"] == "Semarang"
    # 30 / 30 / 40 % of 72 M
    assert [r[2] for r in cd["result"]["tables"][0]["rows"]] == [21_600_000, 21_600_000, 28_800_000]
    texts = [x["text"] for x in cd["checks"]]
    assert "The PBD is not approved yet." in texts and any("above the highest price" in t for t in texts)
    bad = client.post("/api/records/client_decisions", json={"date": "2026-10-05"}, headers=h)
    assert bad.status_code == 422 and "PBD or the project" in bad.json()["detail"]


# --------------------------------------------------------------------------- #
# A.1.6 weekly work plan and budget drawdown
# --------------------------------------------------------------------------- #

def test_work_plan(client, people):
    h = people["mgr"]
    _, p, rate = _base(client, h)
    pbd = _post(client, h, "pbd", _pbd_data(p, rate))
    acts = [{"activity": "Drilling", "start_week": 1, "end_week": 2, "weight_pct": 40},
            {"activity": "Laboratory and report", "start_week": 2, "end_week": 4, "weight_pct": 60}]
    # Gantt: week 1 = 40/2 = 20; week 2 = 20 + 60/3 = 40; weeks 3 and 4 = 20 → 20/40/20/20 %.
    spread = client.post("/api/erp/commercial/work-plans/weeks", json={"activities": acts, "budget": 50_000_000}, headers=h).json()
    assert [(w["week"], w["planned_pct"], w["budget_plan"]) for w in spread] == [
        (1, 20, 10_000_000), (2, 40, 20_000_000), (3, 20, 10_000_000), (4, 20, 10_000_000)]
    weeks = [{"week": 1, "budget_plan": 10_000_000, "drawdown": 10_000_000, "realised": 9_000_000, "actual_pct": 15},
             {"week": 2, "budget_plan": 20_000_000, "drawdown": 20_000_000, "realised": 22_000_000, "actual_pct": 35},
             {"week": 3, "budget_plan": 12_000_000}, {"week": 4, "budget_plan": 8_000_000}]
    wp = _post(client, h, "work_plans", {"date": "2026-10-10", "project_id": p["id"], "pbd_id": pbd["id"], "start_date": "2026-10-12",
                                         "activities": acts, "weeks": weeks})
    assert wp["number"].startswith("WP-2026-") and wp["duration_weeks"] == 4 and wp["report_week"] == 2
    assert wp["total_plan"] == 50_000_000 and wp["pbd_budget"] == 50_000_000 and wp["pbd_weeks"] == 6
    assert wp["total_drawdown"] == 30_000_000 and wp["total_realised"] == 31_000_000
    # Planned to week 2: 20 + 40 = 60 %; actual 15 + 35 = 50 % → 10 points behind.
    assert wp["planned_to_date"] == 60 and wp["actual_to_date"] == 50 and wp["deviation"] == -10
    assert wp["cost_ratio_pct"] == 70.92  # max(plan 50 M, realised 31 M) / bid 70.5 M
    texts = [x["text"] for x in wp["checks"]]
    assert "Realised cost to date is above the budget plan to date." in texts  # 31 M > 30 M
    assert any("behind plan" in t for t in texts) and not any("PBD budget is" in t for t in texts)
    s_curve = wp["result"]["charts"][0]
    assert s_curve["series"][0]["points"] == [[0, 0], [1, 20], [2, 60], [3, 80], [4, 100]]
    assert s_curve["series"][1]["points"] == [[0, 0], [1, 15], [2, 50]]
    row1 = wp["result"]["tables"][0]["rows"][0]
    assert row1[:4] == [1, "2026-10-12", 20, 20]
    # Earned value at week 2: BAC = weekly budget 50 M; PV = 50 M × 60 % = 30 M; EV = 50 M × 50 % = 25 M;
    # AC = 9 + 22 = 31 M. CV = 25 − 31 = −6 M; SV = 25 − 30 = −5 M; CPI = 25/31 = 0.806; SPI = 25/30 = 0.833;
    # EAC = BAC / CPI = 50 × 31 / 25 = 62 M; ETC = 62 − 31 = 31 M; VAC = 50 − 62 = −12 M; TCPI = 25 / 19 = 1.316.
    assert (wp["bac"], wp["bac_source"], wp["pv"], wp["ev"], wp["ac"]) == (50_000_000, "plan", 30_000_000, 25_000_000, 31_000_000)
    assert (wp["cv"], wp["sv"], wp["cpi"], wp["spi"]) == (-6_000_000, -5_000_000, 0.806, 0.833)
    assert (wp["eac"], wp["etc"], wp["vac"], wp["tcpi"]) == (62_000_000, 31_000_000, -12_000_000, 1.316)
    assert any(x["level"] == "warn" and x["vars"].get("index") == "CPI" for x in wp["checks"])
    assert any(x["level"] == "warn" and x["vars"].get("index") == "SPI" for x in wp["checks"])
    assert any("TCPI" in x["text"] for x in wp["checks"]) and any("EAC = BAC / CPI" in x["text"] for x in wp["checks"])
    ev_chart = wp["result"]["charts"][2]
    assert ev_chart["title"] == "Earned value: PV, EV and AC"
    # PV = 50 M × cumulative plan 20/60/80/100 %; EV = 50 M × 15/50 %; AC = 9/31 M (IDR million).
    assert [s_["points"] for s_ in ev_chart["series"]] == [[[0, 0], [1, 10], [2, 30], [3, 40], [4, 50]],
                                                           [[0, 0], [1, 7.5], [2, 25]], [[0, 0], [1, 9], [2, 31]]]
    ev_table = {r[0]: r[1] for r in wp["result"]["tables"][2]["rows"]}
    assert ev_table["Reporting week"] == 2 and ev_table["EAC if the overrun does not recur"] == 56_000_000  # 31 + (50 − 25)
    assert ev_table["EAC with cost and schedule pressure"] == 68_200_000  # 31 + 25 / (25/31 × 25/30) = 31 + 37.2
    # The budget no longer matches the PBD and the plan runs longer than the PBD.
    weeks2 = weeks + [{"week": 7, "budget_plan": 5_000_000}]
    wp2 = _post(client, h, "work_plans", {"date": "2026-10-10", "project_id": p["id"], "pbd_id": pbd["id"], "activities": acts, "weeks": weeks2})
    texts = [x["text"] for x in wp2["checks"]]
    assert any("PBD budget is" in t for t in texts) and any("longer than" in t for t in texts)
    # Without a weekly budget the PBD budget (50 M) is the BAC; without any budget there is no earned value.
    wp3 = _post(client, h, "work_plans", {"date": "2026-10-10", "project_id": p["id"], "pbd_id": pbd["id"], "activities": acts,
                                          "weeks": [{"week": 1, "realised": 9_000_000, "actual_pct": 20}]})
    # PV = EV = 50 M × 20 % = 10 M; CPI = 10 / 9 = 1.111; SPI = 1.
    assert wp3["bac_source"] == "pbd" and wp3["ev"] == 10_000_000 and wp3["cpi"] == 1.111 and wp3["spi"] == 1.0
    wp4 = _post(client, h, "work_plans", {"date": "2026-10-10", "project_id": p["id"], "activities": acts,
                                          "weeks": [{"week": 1, "realised": 9_000_000, "actual_pct": 20}]})
    assert wp4["cpi"] is None and wp4["bac"] is None and any("earned value" in x["text"] for x in wp4["checks"])
    bad = client.post("/api/records/work_plans", json={"date": "2026-10-10", "project_id": p["id"],
                                                         "activities": [{"activity": "x", "start_week": 3, "end_week": 2}]}, headers=h)
    assert bad.status_code == 422
    dup = client.post("/api/records/work_plans", json={"date": "2026-10-10", "project_id": p["id"],
                                                         "weeks": [{"week": 1}, {"week": 1}]}, headers=h)
    assert dup.status_code == 422


# --------------------------------------------------------------------------- #
# A.1.8 contracts, A.1.9 bank guarantees and SKBDN
# --------------------------------------------------------------------------- #

def test_guarantee_and_contract_kinds(client, people):
    h = people["mgr"]
    c, p, _ = _base(client, h)
    _post(client, people["admin"], "settings", {"company_name": "Perusahaan Uji"}, status=201)
    k = _post(client, h, "contracts", {"number": "K-1", "kind": "contract", "project_id": p["id"], "date": "2026-10-01",
                                       "value": 111_000_000, "status": "signed", "end_date": "2027-03-31"})
    sub = _post(client, h, "contracts", {"number": "SUB-1", "kind": "subcontract", "parent_contract_id": k["id"], "project_id": p["id"],
                                         "date": "2026-10-02", "value": 20_000_000, "status": "signed", "subcontractor": "CV Bor"})
    assert sub["kind"] == "subcontract" and sub["parent_contract_id"] == k["id"]
    g = _post(client, people["fin"], "guarantees", {"date": "2026-10-03", "type": "performance", "project_id": p["id"], "contract_id": k["id"],
                                                    "required_pct": 5, "fee_pct": 1, "collateral_pct": 10, "status": "requested",
                                                    "issue_date": "2026-10-05", "expiry_date": "2027-02-28"})
    # 5 % of 111 M = 5,550,000; fee 1 % = 55,500; collateral 10 % = 555,000
    assert g["amount"] == 5_550_000 and g["pct_of_contract"] == 5 and g["fee_amount"] == 55_500 and g["collateral_amount"] == 555_000
    assert g["direction"] == "issued" and g["beneficiary"] == "Klien Uji" and g["number"].startswith("BG-2026-")
    assert any("expires before the contract work ends" in x["text"] for x in g["checks"])
    s = _post(client, h, "guarantees", {"date": "2026-10-03", "type": "skbdn", "project_id": p["id"], "contract_id": k["id"],
                                        "amount": 111_000_000, "status": "requested"})
    assert s["direction"] == "received" and s["beneficiary"] == "Perusahaan Uji" and s["pct_of_contract"] == 100
    bad = client.post("/api/records/guarantees", json={"date": "2026-10-03", "type": "bid", "project_id": p["id"], "status": "requested",
                                                       "issue_date": "2026-10-05", "expiry_date": "2026-10-01"}, headers=h)
    assert bad.status_code == 422
    assert calc.expiry_status({"status": "issued", "expiry_date": "2026-11-10"}, 30, "2026-10-26") == "expiring"
    assert calc.expiry_status({"status": "issued", "expiry_date": "2026-10-25"}, 30, "2026-10-26") == "expired"
    assert calc.expiry_status({"status": "issued", "expiry_date": "2027-01-10"}, 30, "2026-10-26") == "ok"
    assert calc.expiry_status({"status": "released", "expiry_date": "2026-10-25"}, 30, "2026-10-26") == ""
    # The request goes through the approval flow like the other documents.
    _approve(client, people, "guarantees", s["id"])


# --------------------------------------------------------------------------- #
# A.1.10–A.1.14 receivables, NPAR, client card and overview
# --------------------------------------------------------------------------- #

def _invoice(client, h, p, d, due=None, payments=()):
    data = {"project_id": p["id"], "date": d, "status": "sent", "tax_pct": 11, "pph_pct": 2,
            "items": [{"description": "Termin", "qty": 1, "unit_price": 10_000_000}], "payments": list(payments)}
    if due:
        data["due_date"] = due
    return _post(client, h, "invoices", data)


def test_receivables_card_and_overview(client, people):
    adm, mgr = people["admin"], people["mgr"]
    c, p, rate = _base(client, mgr)
    _post(client, mgr, "contracts", {"number": "K-9", "kind": "contract", "project_id": p["id"], "date": "2025-02-01",
                                     "value": 111_000_000, "status": "signed"})
    _post(client, mgr, "contracts", {"number": "S-9", "kind": "subcontract", "project_id": p["id"], "date": "2025-02-02",
                                     "value": 20_000_000, "status": "signed"})
    # Each invoice: 10 M + 11 % VAT = 11.1 M; PPh 23 2 % of 10 M = 200,000 withheld → 10.9 M to collect.
    a = _invoice(client, adm, p, "2026-10-10", "2026-11-09")                 # not yet due, 16 days old
    b = _invoice(client, adm, p, "2026-08-01", "2026-08-31")                 # 56 days overdue, 86 days old
    cc = _invoice(client, adm, p, "2026-06-01")                              # due 1 Jul (30 days), 117 overdue, 147 old → NPAR
    _invoice(client, adm, p, "2026-03-01", "2026-03-31", [{"date": "2026-03-20", "amount": 10_900_000}])  # paid in 19 days
    _invoice(client, adm, p, "2026-04-01", "2026-05-01", [{"date": "2026-05-21", "amount": 10_900_000}])  # paid late, 50 days
    _post(client, adm, "invoices", {"project_id": p["id"], "date": "2026-01-01", "status": "draft",
                                    "items": [{"description": "Draft", "qty": 1, "unit_price": 1_000_000}]})  # not a receivable
    ar = client.get("/api/erp/commercial/receivables?as_of=2026-10-26", headers=mgr).json()
    buckets = {x["key"]: (x["amount"], x["count"]) for x in ar["buckets"]}
    assert buckets == {"current": (10_900_000, 1), "d1_30": (0, 0), "d31_60": (10_900_000, 1), "d61_90": (0, 0), "over_90": (10_900_000, 1)}
    ages = {x["key"]: x["count"] for x in ar["age_buckets"]}
    assert ages == {"lt30": 1, "d30_90": 1, "d91_180": 1, "d181_360": 0, "over_360": 0}
    assert ar["totals"]["outstanding"] == 32_700_000 and ar["totals"]["overdue"] == 21_800_000 and ar["totals"]["npar"] == 10_900_000
    assert ar["totals"]["invoiced"] == 5 * 11_100_000 and ar["totals"]["paid"] == 2 * 10_900_000
    assert [x["id"] for x in ar["npar"]] == [cc["id"]] and ar["npar"][0]["owner"] == "npar" and ar["npar"][0]["days_since_invoice"] == 147
    assert {x["id"]: x["owner"] for x in ar["invoices"]}[b["id"]] == "commercial"
    # Indicative ECL with the example rates: not due 1 % × 10.9 M = 109,000; 56 days overdue 5 % = 545,000;
    # 117 days overdue (91–180) 25 % = 2,725,000 → 3,379,000 = 10.33 % of 32.7 M.
    assert ar["totals"]["ecl"] == 3_379_000 and ar["ecl"]["coverage_pct"] == 10.33

    # Collection note by a manager (who cannot edit invoices otherwise).
    res = client.post(f"/api/erp/commercial/invoices/{cc['id']}/collection-notes",
                      json={"date": "2026-10-26", "action": "npar", "note": "Diserahkan ke Komite NPAR", "next_date": "2026-11-02"}, headers=mgr)
    assert res.status_code == 200, res.text
    assert res.json()["collection_notes"][0]["by"] == "pm@example.com" and res.json()["outstanding"] == 10_900_000
    assert client.put(f"/api/records/invoices/{a['id']}", json={}, headers=mgr).status_code == 403
    assert client.post(f"/api/erp/commercial/invoices/{cc['id']}/collection-notes", json={"action": "call", "note": "x"},
                       headers=people["gen"]).status_code == 403

    card = client.get(f"/api/erp/commercial/clients/{c['id']}/card?as_of=2026-10-26", headers=people["fin"]).json()
    s = card["stats"]
    assert s["projects"] == 1 and s["contract_value"] == 111_000_000  # the subcontract is not client revenue
    assert s["avg_days_to_pay"] == 34.5                                # (19 + 50) / 2
    # Fallen due: 2 paid (1 on time) + 2 open past due → 1 / 4 = 25 %.
    assert s["on_time_rate_pct"] == 25 and s["invoices_due"] == 4 and s["rating"] == "poor"
    assert s["npar"] == 10_900_000 and card["client"]["since_year"] == 2025
    assert card["projects"][0]["outstanding"] == 32_700_000 and card["services"] == {"geotechnical": 1, "laboratory": 1}
    assert card["invoices"][0]["last_note"] is None or card["invoices"][0]["id"] == cc["id"]
    recap = client.get("/api/erp/commercial/clients?as_of=2026-10-26", headers=mgr).json()
    assert recap[0]["id"] == c["id"] and recap[0]["npar"] == 10_900_000

    pbd = _post(client, mgr, "pbd", _pbd_data(p, rate))
    _approve(client, people, "pbd", pbd["id"])
    _post(client, mgr, "work_plans", {"date": "2026-10-10", "project_id": p["id"], "pbd_id": pbd["id"],
                                      "activities": [{"activity": "All", "start_week": 1, "end_week": 2, "weight_pct": 100}],
                                      "weeks": [{"week": 1, "budget_plan": 25_000_000, "realised": 20_000_000, "actual_pct": 40},
                                                {"week": 2, "budget_plan": 25_000_000}]})
    g = _post(client, mgr, "guarantees", {"date": "2026-10-03", "type": "performance", "project_id": p["id"], "amount": 5_000_000,
                                          "status": "issued", "expiry_date": "2026-11-10"})
    ov = client.get("/api/erp/commercial/overview?as_of=2026-10-26", headers=adm).json()
    assert ov["pipeline"]["pbd"] == {"approved": {"count": 1, "value": 70_500_000}}
    assert ov["pipeline"]["projects"] == {"tender": 1}
    assert ov["contracts"]["value"] == 111_000_000 and ov["contracts"]["by_kind"]["subcontract"]["value"] == 20_000_000
    assert ov["receivables"]["npar"] == 10_900_000 and len(ov["npar"]) == 1
    plan = ov["projects_budget"][0]
    assert plan["pbd_budget"] == 50_000_000 and plan["realised"] == 20_000_000 and plan["planned_pct"] == 50 and plan["actual_pct"] == 40
    # BAC 50 M, PV 25 M, EV 20 M, AC 20 M → CPI 1.0, SPI 0.8; EAC = BAC.
    assert (plan["cpi"], plan["spi"], plan["eac"], plan["vac"]) == (1.0, 0.8, 50_000_000, 0)
    assert ov["ecl"]["total"] == 3_379_000 and ov["receivables"]["ecl"] == 3_379_000 and ov["evm_warning_index"] == 0.9
    assert ov["clients_by_province"] == [{"key": "JT", "clients": 1, "projects": 1, "contract_value": 111_000_000,
                                          "label": "Jawa Tengah", "zone": "C"}]
    assert {r["key"] for r in ov["clients_by_service"]} == {"geotechnical", "laboratory"}
    assert ov["guarantees"]["expiring"][0]["id"] == g["id"] and ov["guarantees"]["expiring"][0]["days"] == 15
    assert ov["cost_ratio"]["average_pct"] == 70.92
    # Field staff do not see the commercial figures.
    assert client.get("/api/erp/commercial/overview", headers=people["gen"]).status_code == 403
    assert client.get("/api/erp/commercial/receivables", headers=people["gen"]).status_code == 403


def test_pricing_config_defaults_and_settings(client, people):
    cfg = client.get("/api/erp/commercial/config", headers=people["mgr"]).json()
    assert cfg["factors_source"] == "default" and len(cfg["factors"]) == 16 and cfg["max_cost_ratio_pct"] == 75
    assert [x["premium_pct"] for x in cfg["premiums"]] == [5, 8, 11, 14, 17] and cfg["province_zone"]["BT"] == "A"
    assert cfg["ecl_source"] == "default" and [x["rate_pct"] for x in cfg["ecl_rates"]] == [1, 2, 5, 10, 25, 50, 100]
    assert cfg["evm_warning_index"] == 0.9 and cfg["ahsp_indirect_pct"] == [10, 15] and cfg["consultancy_direct_max_pct"] == 40
    _post(client, people["admin"], "settings", {
        "company_name": "Perusahaan Uji", "max_cost_ratio_pct": 65, "default_margin_pct": 25,
        "evm_warning_index": 0.85, "ecl_rates": [{"bucket": "over_360", "rate_pct": 80}],
        "difficulty_factors": [{"key": "zone", "factor": "Region zone", "weight": 1}, {"factor": "Access", "weight": 1}],
        "risk_premium_table": [{"index": 1, "premium_pct": 4}],
        "approval_limits": [{"up_to": 1_000_000, "level": "Manager"}, {"level": "Director"}]}, status=201)
    cfg = client.get("/api/erp/commercial/config", headers=people["mgr"]).json()
    assert cfg["factors_source"] == "settings" and [f["key"] for f in cfg["factors"]] == ["zone", "access"]
    assert cfg["premiums"][0]["premium_pct"] == 4 and cfg["default_margin_pct"] == 25
    assert cfg["evm_warning_index"] == 0.85 and cfg["ecl_source"] == "settings" and cfg["ecl_rates"][-1]["rate_pct"] == 80
    bad = client.put("/api/records/settings/" + client.get("/api/records/settings", headers=people["admin"]).json()[0]["id"],
                     json={"company_name": "Perusahaan Uji", "evm_warning_index": 1.5}, headers=people["admin"])
    assert bad.status_code == 422  # the threshold is an index between 0.5 and 1
    _, p, rate = _base(client, people["mgr"])
    # Zone C scores 1, access 1 → index 1 → 4 %; margin 25 % by default; bid above 1 M → "Director".
    pbd = _post(client, people["mgr"], "pbd", {"date": "2026-10-01", "project_id": p["id"], "difficulty": [{"key": "access", "score": 1}],
                                               "costs": [{"section": "other", "description": "x", "qty": 1, "unit_cost": 1_000_000}]})
    assert pbd["risk_premium_pct"] == 4 and pbd["margin_pct"] == 25 and pbd["bid_price"] == 1_290_000
    assert pbd["approval_level"] == "Director" and pbd["max_cost_ratio_pct"] == 65
    assert client.get("/api/erp/commercial/config", headers=people["gen"]).status_code == 403
    assert calc.approval_level(500_000, {"approval_limits": [{"up_to": 1_000_000, "level": "Manager"}]}) == "Manager"
    assert calc.approval_level(3e9, None) == "Approvers 1 and 2" and calc.approval_level(2e10, None) == "Approvers 1 to 4"


def test_contract_values_and_gantt_rounding():
    projects = [{"id": "a", "status": "tender", "contract_value": 5e8}, {"id": "b", "status": "ongoing", "contract_value": 3e8},
                {"id": "c", "status": "completed", "contract_value": 9e8}]
    contracts = [{"project_id": "c", "kind": "contract", "status": "signed", "value": 1e9},
                 {"project_id": "c", "kind": "spmk", "status": "signed", "value": 1e9}]
    # A tender's estimate is not a contract; a signed contract wins over the project's value; an SPMK is not counted again.
    assert calc.contract_values(projects, contracts) == {"b": 3e8, "c": 1e9}
    weeks = calc.weeks_from_gantt([{"activity": "x", "start_week": 1, "end_week": 3, "weight_pct": 100}], 1_000_000)
    assert [w["planned_pct"] for w in weeks] == [33.33, 33.33, 33.34]
    assert [w["budget_plan"] for w in weeks] == [333_333, 333_333, 333_334]


def test_earned_value_bands_and_edge_cases():
    # CPI = SPI = 47 / 50 = 0.94: between 0.90 and 0.95 → only "watch" remarks.
    # EAC = 100 M × 50 / 47 = 106,382,978.7 → 106,382,979; TCPI = 53 / 50 = 1.06 (not above 1.10).
    out = calc.earned_value(100_000_000, 50, 47, 50_000_000)
    assert out["cpi"] == 0.94 and out["spi"] == 0.94 and out["eac"] == 106_382_979 and out["vac"] == -6_382_979 and out["tcpi"] == 1.06
    assert [c["level"] for c in out["checks"]] == ["info", "info"]
    # A company threshold of 0.80 turns the 0.806 CPI of the work plan test into a "watch" remark.
    out = calc.earned_value(50_000_000, 60, 50, 31_000_000, warning_index=0.80)
    assert [c["level"] for c in out["checks"] if c["vars"].get("index") == "CPI"] == ["info"]
    # Budget used up with 40 % of the work left: TCPI cannot be met (BAC − AC = 0).
    out = calc.earned_value(10_000_000, 80, 60, 10_000_000)
    assert out["tcpi"] is None and out["eac"] == 16_666_667 and any(c["level"] == "error" for c in out["checks"])  # 10 M / 0.6
    # No cost reported yet: no CPI and no EAC; TCPI = (100 − 30) / 100 = 0.7.
    out = calc.earned_value(100_000_000, 30, 30, 0)
    assert out["cpi"] is None and out["eac"] is None and out["spi"] == 1.0 and out["tcpi"] == 0.7 and out["checks"] == []


def test_pbd_government_cost_reference(client, people):
    h = people["mgr"]
    _, p, rate = _base(client, h)
    # AHSP: risk 11 % + margin 30 % = 41 % of the ABP, above the 10–15 % of Permen PUPR 8/2023 Art. 11(3).
    pbd = _post(client, h, "pbd", _pbd_data(p, rate, cost_reference="ahsp"))
    assert pbd["indirect_pct"] == 41 and pbd["bid_price"] == 70_500_000
    assert any(x["level"] == "warn" and "Art. 11(3)" in x["text"] for x in pbd["checks"])
    values = {v["label"]: v["value"] for v in pbd["result"]["values"]}
    assert values["ABP + 15% indirect cost (AHSP reference)"] == 57_500_000  # 50 M × 1.15
    # 0 % + 12 % sits inside the range: no remark; 0 % + 8 % is below it.
    ok = _post(client, h, "pbd", _pbd_data(p, rate, cost_reference="ahsp", risk_pct_override=0, margin_pct=12))
    assert ok["indirect_pct"] == 12 and not any("Art. 11(3)" in x["text"] for x in ok["checks"])
    low = _post(client, h, "pbd", _pbd_data(p, rate, cost_reference="ahsp", risk_pct_override=0, margin_pct=8))
    assert any(x["level"] == "info" and "below the 10–15%" in x["text"] for x in low["checks"])
    # Consultancy without personnel lines: non-personnel = 50 M / 70.5 M = 70.92 % of the bid.
    cons = _post(client, h, "pbd", _pbd_data(p, rate, cost_reference="consultancy"))
    texts = [x["text"] for x in cons["checks"]]
    assert any("personnel (labour) lines" in t for t in texts) and any("INKINDO 2025" in t for t in texts)
    assert {v["label"]: v["value"] for v in cons["result"]["values"]}["Non-personnel cost (% of the bid price)"] == 70.92
    # Personnel 30 M + equipment 10 M, margin 50 %: bid 60 M, non-personnel 10 / 60 = 16.67 % → no remark.
    cons2 = _post(client, h, "pbd", {"date": "2026-10-01", "project_id": p["id"], "cost_reference": "consultancy",
                                     "risk_pct_override": 0, "margin_pct": 50, "costs": [
                                         {"section": "labour", "description": "Geotechnical engineer", "qty": 3, "unit_cost": 10_000_000},
                                         {"section": "equipment", "description": "Rig rental", "qty": 1, "unit_cost": 10_000_000}]})
    assert cons2["bid_price"] == 60_000_000 and not any("INKINDO" in x["text"] for x in cons2["checks"])
    assert {v["label"]: v["value"] for v in cons2["result"]["values"]}["Non-personnel cost (% of the bid price)"] == 16.67
    # A government client without a reference gets a reminder; a private client does not.
    gov = _post(client, h, "clients", {"name": "Dinas Uji", "type": "government"})
    gp = _post(client, h, "projects", {"code": "P-G", "name": "Proyek Pemerintah", "client_id": gov["id"], "status": "tender"})
    g = _post(client, h, "pbd", _pbd_data(gp, rate))
    assert any("Government client" in x["text"] for x in g["checks"])
    assert not any("Government client" in x["text"] for x in pbd["checks"])


def test_expected_credit_loss_provision_matrix():
    projects = [{"id": "p", "client_id": "c", "name": "P"}]
    clients = [{"id": "c", "name": "C"}]

    def inv(i, issued, due, amount):
        return {"id": i, "number": i, "project_id": "p", "status": "sent", "date": issued, "due_date": due,
                "total": amount, "paid": 0, "outstanding": amount}

    invoices = [inv("a", "2026-10-01", "2026-10-31", 10_000_000),   # not yet due on 26 Oct
                inv("b", "2026-08-01", "2026-09-15", 10_000_000),   # 41 days overdue
                inv("c", "2026-03-01", "2026-04-01", 10_000_000),   # 208 days overdue
                inv("d", "2025-01-01", "2025-02-01", 4_000_000)]    # 632 days overdue
    ar = calc.receivables(invoices, projects, clients, None, "2026-10-26")
    # Example rates: 1 % × 10 M + 5 % × 10 M + 50 % × 10 M + 100 % × 4 M = 0.1 + 0.5 + 5 + 4 = 9.6 M of 34 M (28.24 %).
    by = {b["key"]: (b["amount"], b["rate_pct"], b["ecl"]) for b in ar["ecl"]["buckets"]}
    assert by["current"] == (10_000_000, 1.0, 100_000) and by["d31_60"] == (10_000_000, 5.0, 500_000)
    assert by["d181_360"] == (10_000_000, 50.0, 5_000_000) and by["over_360"] == (4_000_000, 100.0, 4_000_000)
    assert ar["ecl"]["total"] == 9_600_000 and ar["totals"]["ecl"] == 9_600_000 and ar["ecl"]["coverage_pct"] == 28.24
    assert ar["ecl"]["source"] == "default" and ar["by_client"][0]["ecl"] == 9_600_000
    # Finance sets its own rate for 181–360 days: 40 % → 4 M instead of 5 M.
    ar = calc.receivables(invoices, projects, clients, {"ecl_rates": [{"bucket": "d181_360", "rate_pct": 40}]}, "2026-10-26")
    assert ar["ecl"]["total"] == 8_600_000 and ar["ecl"]["source"] == "settings"
    assert {r["id"]: r["ecl"] for r in ar["invoices"]} == {"a": 100_000, "b": 500_000, "c": 4_000_000, "d": 4_000_000}
