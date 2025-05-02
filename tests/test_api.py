import os
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def client_app():
    return client


@pytest.fixture(scope="module")
def auth_headers(client_app):
    token_resp = client_app.post(
        "/token", data={"username": os.getenv("TEST_USER", "testuser"), "password": os.getenv("TEST_PASS", "testpassword")}
    )
    assert token_resp.status_code == 200
    token = token_resp.json().get("access_token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_create_and_get_scenario(client_app, auth_headers):
    payload = {"nom": "API Test", "description": "desc", "priorite": "moyenne", "documents": [], "variables": []}
    resp = client_app.post("/scenarios/", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    sid = resp.json().get("scenario_id")
    assert sid
    get = client_app.get(f"/scenarios/{sid}", headers=auth_headers)
    assert get.status_code == 200
    assert get.json()["scenario"]["id"] == sid


def test_run_scenario(client_app, auth_headers):
    payload = {"nom": "Run Test", "description": "run", "priorite": "basse", "documents": [], "variables": []}
    sid = client_app.post("/scenarios/", json=payload, headers=auth_headers).json()["scenario_id"]
    run = client_app.post(f"/scenarios/{sid}/run", headers=auth_headers)
    assert run.status_code == 200
    assert "status" in run.json()


@pytest.mark.skipif(os.getenv("MINIO_ENDPOINT") is None, reason="MinIO not configured")
def test_file_upload_download(client_app, auth_headers):
    data = b"hello world"
    files = {"file": ("hello.txt", data, "text/plain")}
    up = client_app.post("/upload/", files=files, headers=auth_headers)
    assert up.status_code == 200
    fname = up.json().get("filename")
    assert fname == "hello.txt"
    down = client_app.get(f"/download/{fname}", headers=auth_headers)
    assert down.status_code == 200
    assert down.content == data


def test_variable_crud(client_app, auth_headers):
    create = client_app.post("/variables/", json={"id": None, "key": "k", "data_type": "string", "value": "v"}, headers=auth_headers)
    vid = create.json().get("variable_id")
    assert vid
    get = client_app.get(f"/variables/{vid}", headers=auth_headers)
    assert get.status_code == 200
    delr = client_app.delete(f"/variables/{vid}", headers=auth_headers)
    assert delr.status_code == 200


def test_automation_crud(client_app, auth_headers):
    sid = client_app.post("/scenarios/", json={"nom": "AutoTest", "description": "x", "priorite": "moyenne", "documents": [], "variables": []}, headers=auth_headers).json()["scenario_id"]
    auto = client_app.post("/automatisations/", json={"scenario_id": sid, "agent_config": {"model": "test"}}, headers=auth_headers)
    aid = auto.json().get("automatisation_id")
    assert aid
    get = client_app.get(f"/automatisations/{aid}", headers=auth_headers)
    assert get.status_code == 200
    delr = client_app.delete(f"/automatisations/{aid}", headers=auth_headers)
    assert delr.json().get("status") == "deleted"
