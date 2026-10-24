import os
import tempfile

# Must be set before the app modules are imported (they read it at import time).
_TMP = tempfile.mkdtemp(prefix="soilboring-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ["AUTH_TOKEN_SECRET"] = "test-secret-" + "x" * 32
os.environ.pop("OLLAMA_URL", None)

import pytest
from fastapi.testclient import TestClient

from backend.app import analytics, auth, docstore
from backend.app.main import app


@pytest.fixture(autouse=True)
def clean_state():
    docstore.reset_all_for_tests()
    auth.reset_login_throttle()
    analytics.clear_ai_cache()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_user(email, password="correct-horse-1", role="general"):
    auth.create_user(email, password, role)
    return email, password


@pytest.fixture
def admin_headers(client):
    email, password = make_user("admin@example.com", role="admin")
    return login_headers(client, email, password)


@pytest.fixture
def general_headers(client, admin_headers):
    email, password = make_user("worker@example.com", role="general")
    return login_headers(client, email, password)


def login_headers(client, email, password):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def sample_report(**overrides):
    data = {
        "BoreholeID": "BH-001",
        "ProjectName": "Proyek Jalan Layang",
        "SiteName": "Zona A",
        "Latitude": "-6.176",
        "Longitude": "106.865",
        "StartDate": "2026-03-10",
        "EndDate": "2026-03-11",
        "DrillingMethod": "Wash Boring + SPT",
        "FinalDepth_m": "30.0",
        "TargetDepth_m": "30",
        "GroundwaterEncountered": True,
        "GroundwaterDepth_m": "2.8",
        "USCS_Class": "CL",
        "Avg_SPT_N60": "14",
        "Contractor": "PT GeoBore",
        "Remarks": "Lapisan lempung, lunak",
    }
    data.update(overrides)
    return data
