"""Approval flow: Konseptor → Pengulas → Pemutus, separation of duties, locks and the inbox."""


from .conftest import login_headers, make_user


def _user(client, admin_headers, email, role):
    return login_headers(client, *make_user(email, role=role))


def test_contract_approval_flow(client, admin_headers):
    mgr = _user(client, admin_headers, "pm@example.com", "manager")
    mgr2 = _user(client, admin_headers, "pm2@example.com", "manager")
    c = client.post("/api/records/clients", json={"name": "Klien WF", "type": "private"}, headers=admin_headers).json()
    p = client.post("/api/records/projects", json={"code": "WF-1", "name": "WF", "client_id": c["id"], "status": "contract"}, headers=admin_headers).json()
    k = client.post("/api/records/contracts", json={"number": "K-WF-1", "project_id": p["id"], "date": "2026-10-01", "value": 1000000, "status": "draft"}, headers=mgr)
    assert k.status_code == 201, k.text
    k = k.json()
    assert k["wf_status"] == "draft"
    url = f"/api/records/contracts/{k['id']}/workflow"
    assert client.post(url, json={"action": "review"}, headers=mgr).status_code == 409  # not submitted yet
    assert client.post(url, json={"action": "submit"}, headers=mgr).json()["wf_status"] == "submitted"
    # The drafter cannot review their own submission; another manager can, after which it is locked for managers.
    assert client.post(url, json={"action": "review"}, headers=mgr).status_code == 409
    assert client.post(url, json={"action": "return"}, headers=mgr2).status_code == 409  # a return needs a note
    assert client.post(url, json={"action": "review"}, headers=mgr2).json()["wf_status"] == "reviewed"
    put = client.put(f"/api/records/contracts/{k['id']}", json={"number": "K-WF-1", "project_id": p["id"], "date": "2026-10-01", "value": 2, "status": "draft"}, headers=mgr2)
    assert put.status_code == 409
    inbox = client.get("/api/approvals", headers=admin_headers).json()
    assert any(i["id"] == k["id"] and i["state"] == "reviewed" for i in inbox)
    assert client.post(url, json={"action": "return", "note": "Nilai kontrak dicek ulang"}, headers=admin_headers).json()["wf_status"] == "submitted"
    assert client.post(url, json={"action": "review"}, headers=mgr2).json()["wf_status"] == "reviewed"
    done = client.post(url, json={"action": "approve"}, headers=admin_headers).json()
    assert done["wf_status"] == "approved" and [h["action"] for h in done["wf_history"]] == ["submit", "review", "return", "review", "approve"]
    assert client.delete(f"/api/records/contracts/{k['id']}", headers=admin_headers).status_code == 409
    assert client.post(url, json={"action": "reopen", "note": "Adendum"}, headers=admin_headers).json()["wf_status"] == "draft"
    # Readonly approval fields cannot be set by a save.
    put = client.put(f"/api/records/contracts/{k['id']}", json={"number": "K-WF-1", "project_id": p["id"], "date": "2026-10-01", "value": 5, "status": "draft",
                                                                "wf_status": "approved"}, headers=admin_headers).json()
    assert put["wf_status"] == "draft"
