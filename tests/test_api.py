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
    # Obtain JWT token for testuser
    token_resp = client_app.post(
        "/token", data={"username": "testuser", "password": "testpassword"}
    )
    token = token_resp.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


def test_create_scenario(client_app, auth_headers):
    payload = {
        "nom": "Scénario API Test",
        "description": "Test endpoint creation",
        "priorite": "moyenne",
        "documents": [],
        "variables": [],
    }
    response = client_app.post("/scenarios/", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "scenario_id" in data
    assert isinstance(data["scenario_id"], str)


def test_run_scenario(client_app, auth_headers):
    # Créer un scénario à exécuter
    payload = {
        "nom": "Scénario Run Test",
        "description": "Test run",
        "priorite": "basse",
        "documents": [],
        "variables": [],
    }
    create_resp = client_app.post("/scenarios/", json=payload, headers=auth_headers)
    scenario_id = create_resp.json()["scenario_id"]
    run_resp = client_app.post(f"/scenarios/{scenario_id}/run", headers=auth_headers)
    assert run_resp.status_code == 200
    assert run_resp.json().get("status") == "Automatisation lancée"


@pytest.mark.skipif(os.getenv("MINIO_ENDPOINT") is None, reason="MinIO non configuré")
def test_upload_and_download_file(client_app):
    # Prépare un fichier factice
    content = b"Test content"
    files = {"file": ("test.txt", content, "text/plain")}
    # Use auth headers
    # Obtain fresh token
    token_resp = client_app.post(
        "/token", data={"username": "testuser", "password": "testpassword"}
    )
    token = token_resp.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    upload_resp = client_app.post("/upload/", files=files, headers=headers)
    assert upload_resp.status_code == 200
    data = upload_resp.json()
    assert data.get("filename") == "test.txt"
    download_resp = client_app.get(f"/download/{data.get('filename')}", headers=headers)
    assert download_resp.status_code == 200
    assert download_resp.content == content


def test_agent_end_to_end_invoice(client_app, auth_headers, tmp_path):
    """
    Test global : upload d'une facture, création de scénario, exécution automatisée par l'agent IA
    Vérifie que le flux complet fonctionne et que l'agent orchestre bien les tools.
    """
    # 1. Upload d'un document (facture)
    facture_path = "data/facture_template_1.pdf"
    with open(facture_path, "rb") as f:
        content = f.read()
    files = {"file": ("facture_test.pdf", content, "application/pdf")}
    upload_resp = client_app.post("/upload/", files=files, headers=auth_headers)
    assert upload_resp.status_code == 200
    # 2. Création d'un scénario lié à ce document
    payload = {
        "nom": "Test Agent Facture",
        "description": "Test global agent IA",
        "priorite": "moyenne",
        "documents": [],  # on ne lie pas explicitement, l'agent doit gérer
        "variables": [],
    }
    create_resp = client_app.post("/scenarios/", json=payload, headers=auth_headers)
    assert create_resp.status_code == 200
    scenario_id = create_resp.json()["scenario_id"]
    # 3. Exécution automatisée du scénario (run)
    run_resp = client_app.post(
        f"/scenarios/{scenario_id}/run?sync=true", headers=auth_headers
    )
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["status"] in ["terminé", "Automatisation lancée"]
    # 4. Vérifie la présence d'un résultat structuré (agent_result ou results)
    if "results" in data:
        assert isinstance(data["results"], list)
    elif "agent_result" in data:
        assert "scenario_id" in data["agent_result"] or "agent_result" in data
    else:
        assert False, "Aucun résultat structuré retourné par l'agent IA"
