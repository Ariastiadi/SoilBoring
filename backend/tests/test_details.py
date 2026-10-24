import base64

from backend.app import audit, details

from .conftest import login_headers, make_user, sample_report

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200


def _log(client, headers, **overrides):
    res = client.post("/api/reports", json=sample_report(**overrides), headers=headers)
    assert res.status_code == 201, res.text


def test_depth_data_roundtrip_and_validation(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-7")
    body = {
        "layers": [{"top": 2, "base": 5, "uscs": "sm"}, {"top": 0, "base": 2, "uscs": "CH", "description": "Lempung"}],
        "spt": [{"depth": 3, "seat": 2, "inc1": 5, "inc2": 6}],
        "samples": [{"top": 1, "base": 1.5, "type": "U", "ref": "U1"}],
        "core": [],
    }
    res = client.put("/api/details/bh-7", json=body, headers=admin_headers)
    assert res.status_code == 200, res.text
    data = client.get("/api/details/BH-7", headers=admin_headers).json()
    assert data["borehole_id"] == "BH-7"
    assert [l["top"] for l in data["layers"]] == [0, 2]  # sorted
    assert data["layers"][1]["uscs"] == "SM"
    assert data["spt"][0]["n"] == 11 and data["spt"][0]["reported"] == "N=11"
    bad = dict(body, layers=[{"top": 0, "base": 3}, {"top": 2, "base": 5}])
    assert client.put("/api/details/BH-7", json=bad, headers=admin_headers).status_code == 422
    bad = dict(body, core=[{"top": 1, "base": 2, "tcr": 50, "scr": 60}])
    assert client.put("/api/details/BH-7", json=bad, headers=admin_headers).status_code == 422
    bad = dict(body, samples=[{"top": 1, "type": "ZZ"}])
    assert client.put("/api/details/BH-7", json=bad, headers=admin_headers).status_code == 422
    assert client.get("/api/details/NOPE", headers=admin_headers).status_code == 404


def test_only_owner_or_admin_edits_depth_data_and_photos(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-8")
    email, password = make_user("op@example.com", role="general")
    other = login_headers(client, email, password)
    assert client.get("/api/details/BH-8", headers=other).status_code == 200
    assert client.put("/api/details/BH-8", json={"layers": []}, headers=other).status_code == 403
    photo = {"borehole_id": "BH-8", "content_type": "image/jpeg", "data_base64": base64.b64encode(JPEG).decode()}
    assert client.post("/api/photos", json=photo, headers=other).status_code == 403


def test_photos_upload_read_delete_and_cleanup(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-9")
    photo = {"borehole_id": "BH-9", "content_type": "image/jpeg", "data_base64": base64.b64encode(JPEG).decode(),
             "caption": "Core box 1", "depth": 25}
    res = client.post("/api/photos", json=photo, headers=admin_headers)
    assert res.status_code == 201, res.text
    photo_id = res.json()["id"]
    got = client.get(f"/api/photos/{photo_id}", headers=admin_headers)
    assert got.status_code == 200 and got.content == JPEG and got.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/photos/{photo_id}").status_code == 401
    fake = dict(photo, data_base64=base64.b64encode(b"not an image").decode())
    assert client.post("/api/photos", json=fake, headers=admin_headers).status_code == 422
    assert client.get("/api/details/BH-9", headers=admin_headers).json()["photos"][0]["caption"] == "Core box 1"
    # Deleting the log removes its depth data and photos too.
    assert client.delete("/api/reports/BH-9", headers=admin_headers).status_code == 200
    assert details.read_photo(photo_id) is None
    assert details.get_details("BH-9")["photos"] == []
    assert client.get("/api/photos/../../etc/passwd", headers=admin_headers).status_code == 404


def test_activity_log_records_changes(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-10")
    client.put("/api/reports/BH-10", json={"Remarks": "baru"}, headers=admin_headers)
    client.put("/api/details/BH-10", json={"layers": [{"top": 0, "base": 1}]}, headers=admin_headers)
    events = client.get("/api/audit?target=BH-10", headers=admin_headers).json()
    actions = [e["action"] for e in events]
    assert actions[:3] == ["depth_data.updated", "log.updated", "log.created"]
    assert events[1]["changes"]["Remarks"][1] == "baru"
    assert events[1]["user"] == "admin@example.com"
    email, password = make_user("op2@example.com", role="general")
    other = login_headers(client, email, password)
    assert client.get("/api/audit", headers=other).status_code == 403
    assert client.get("/api/audit?target=BH-10", headers=other).status_code == 200
    assert all("password" not in str(e).lower() for e in audit.list_events())


def test_ai_context_includes_depth_data(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-11")
    client.put("/api/details/BH-11", json={
        "layers": [{"top": 0, "base": 4, "uscs": "CH", "description": "Lempung lunak"}],
        "spt": [{"depth": 2, "seat": 1, "inc1": 2, "inc2": 3}, {"depth": 10, "seat": 30, "inc1": 50, "penetration_mm": 90}],
    }, headers=admin_headers)
    body = client.post("/api/ai/prompt", json={"question": "BH-11 strata"}, headers=admin_headers).json()
    assert "0-4 CH Lempung lunak" in body["context"]
    assert "2:5; 10:50/90mm" in body["context"]


def test_account_events_are_not_visible_through_a_borehole_named_like_an_email(client, admin_headers):
    email, password = make_user("snoop@example.com", role="general")
    other = login_headers(client, email, password)
    make_user("victim@example.com", role="general")
    client.put("/api/users/victim@example.com/password", json={"password": "reset-by-admin"}, headers=admin_headers)
    assert client.post("/api/reports", json=sample_report(BoreholeID="victim@example.com"), headers=other).status_code == 201
    events = client.get("/api/audit?target=VICTIM@example.com", headers=other).json()
    assert [e["action"] for e in events] == ["log.created"]


def test_nan_and_tiny_or_duplicate_depths_are_rejected(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-N")
    res = client.put("/api/details/BH-N", content='{"layers":[{"top":NaN,"base":2}]}',
                     headers={**admin_headers, "Content-Type": "application/json"})
    assert res.status_code == 422
    assert client.put("/api/details/BH-N", json={"layers": [{"top": 1.001, "base": 1.003}]}, headers=admin_headers).status_code == 422
    spt = [{"depth": 1.501, "seat": 1, "inc1": 1}, {"depth": 1.504, "seat": 1, "inc1": 1}]
    assert client.put("/api/details/BH-N", json={"spt": spt}, headers=admin_headers).status_code == 422
    same = [{"top": 1, "type": "D", "ref": "é1"}, {"top": 2, "type": "D", "ref": "E1"}]
    assert client.put("/api/details/BH-N", json={"samples": same}, headers=admin_headers).status_code == 422


def test_concurrent_edit_is_refused_instead_of_lost(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-C")
    first = client.put("/api/details/BH-C", json={"layers": [{"top": 0, "base": 1}]}, headers=admin_headers).json()
    stamp = first["updated_at"]
    ok = client.put("/api/details/BH-C", json={"layers": [{"top": 0, "base": 2}], "expected_updated_at": stamp}, headers=admin_headers)
    assert ok.status_code == 200
    stale = client.put("/api/details/BH-C", json={"layers": [{"top": 0, "base": 3}], "expected_updated_at": stamp}, headers=admin_headers)
    assert stale.status_code == 409


def test_recreated_id_starts_without_old_depth_data(client, admin_headers):
    _log(client, admin_headers, BoreholeID="BH-R")
    details.save_details("BH-R", details.DetailsIn.model_validate({"layers": [{"top": 0, "base": 1}]}), "x@example.com")
    client.delete("/api/reports/BH-R", headers=admin_headers)
    details.save_details("BH-R", details.DetailsIn.model_validate({"layers": [{"top": 0, "base": 1}]}), "x@example.com")  # stray leftover
    _log(client, admin_headers, BoreholeID="BH-R")
    assert client.get("/api/details/BH-R", headers=admin_headers).json()["layers"] == []
