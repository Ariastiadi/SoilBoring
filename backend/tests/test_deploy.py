"""Single-service deployment: the API also serves the built UI (root Dockerfile)."""
import importlib

from fastapi.testclient import TestClient


def test_public_config_exposes_only_org_name(client, monkeypatch):
    from backend.app import config

    monkeypatch.setattr(config, "ORG_NAME", "Soilens")
    assert client.get("/api/config").json() == {"org_name": "Soilens", "app_name": "Soil Boring Ops"}


def test_serves_built_ui_with_spa_fallback(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>ui</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    from backend.app import main

    module = importlib.reload(main)
    try:
        with TestClient(module.app) as c:
            page = c.get("/")
            assert page.status_code == 200 and "<title>ui</title>" in page.text
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            asset = c.get("/assets/app.js")
            assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
            assert c.get("/some/client/route").text == page.text
            assert c.get("/../secret.txt").text == page.text  # no escape from the UI folder
            assert c.get("/api/health").json() == {"status": "ok"}
            assert c.get("/api/unknown").status_code == 404
            assert c.get("/api/reports").status_code == 401
            assert c.get("/assets/missing.js").status_code == 404
            assert c.get("/%00").status_code == 200
            assert c.get("/" + "a" * 300).status_code == 200
            assert "content-security-policy" not in c.get("/docs").headers
    finally:
        monkeypatch.delenv("FRONTEND_DIST")
        importlib.reload(main)


def test_head_request_on_ui(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html>")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    from backend.app import main

    module = importlib.reload(main)
    try:
        with TestClient(module.app) as c:
            assert c.head("/").status_code == 200
    finally:
        monkeypatch.delenv("FRONTEND_DIST")
        importlib.reload(main)
