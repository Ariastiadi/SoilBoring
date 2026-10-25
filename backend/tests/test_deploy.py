"""Single-service deployment: the API also serves the built UI (root Dockerfile)."""
import importlib
import os

from fastapi.testclient import TestClient


def test_public_config_exposes_only_org_name(client, monkeypatch):
    from backend.app import config

    monkeypatch.setattr(config, "ORG_NAME", "Soilens")
    assert client.get("/api/config").json() == {"org_name": "Soilens", "app_name": "Soil Boring Ops", "ai_server": False, "email_reset": False}


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
            csp = page.headers["content-security-policy"]
            assert "frame-ancestors 'none'" in csp
            # On-device AI: WebAssembly, blob workers, model from Hugging Face, engine from jsDelivr.
            assert "'wasm-unsafe-eval'" in csp and "worker-src 'self' blob:" in csp
            assert "https://huggingface.co" in csp and "https://cdn.jsdelivr.net" in csp
            assert page.headers["cross-origin-opener-policy"] == "same-origin"
            assert page.headers["cross-origin-embedder-policy"] == "require-corp"
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


def test_vercel_dependency_list_matches_requirements():
    """pyproject.toml (Vercel) and backend/requirements.txt (Docker, dev) must not drift apart."""
    import pathlib

    import pytest

    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    root = pathlib.Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    requirements = [
        line.split("#", 1)[0].strip()
        for line in (root / "backend" / "requirements.txt").read_text().splitlines()
    ]
    assert project["project"]["dependencies"] == [r for r in requirements if r]
    assert project["tool"]["vercel"]["entrypoint"] == "backend.app.main:app"


def test_vercel_defaults(tmp_path, monkeypatch):
    """On Vercel the UI comes from frontend/dist and files may only be written under /tmp."""
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    config = json.loads((root / "vercel.json").read_text())
    assert "backend/app/main.py" in config["functions"]
    assert "frontend/dist" not in config["functions"]["backend/app/main.py"]["excludeFiles"]

    original_data_dir = os.environ.get("DATA_DIR")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    from backend.app import docstore, main

    try:
        docstore.close_pool()
        importlib.reload(docstore)
        assert docstore.ON_VERCEL
        assert docstore.DATA_PATH.as_posix() == "/tmp/soilboring-data"
        module = importlib.reload(main)
        assert module._FRONTEND == (root / "frontend" / "dist").resolve()
    finally:
        # Put the shared modules back the way the other tests expect them.
        monkeypatch.delenv("VERCEL")
        if original_data_dir is not None:
            monkeypatch.setenv("DATA_DIR", original_data_dir)
        docstore.close_pool()
        importlib.reload(docstore)
        importlib.reload(main)


def test_app_shell_etag_follows_content(tmp_path, monkeypatch):
    """A new release of index.html with the same size and mtime must get a new ETag."""
    import os

    index = tmp_path / "index.html"
    index.write_text("<script src=/assets/index-AAAA.js></script>")
    os.utime(index, (315532800, 315532800))
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    from backend.app import main

    module = importlib.reload(main)
    try:
        with TestClient(module.app) as c:
            first = c.get("/").headers["etag"]
            index.write_text("<script src=/assets/index-BBBB.js></script>")
            os.utime(index, (315532800, 315532800))
            second = c.get("/")
            assert second.headers["etag"] != first and "BBBB" in second.text
            assert second.headers["cache-control"] == "no-cache"
            assert c.get("/sw.js").headers["etag"] == second.headers["etag"]  # SPA fallback
    finally:
        monkeypatch.delenv("FRONTEND_DIST")
        importlib.reload(main)
