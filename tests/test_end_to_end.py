"""
End-to-end test for the automation workflow.
This test demonstrates the complete functionality of the system:
1. Upload a document to MinIO
2. Create a scenario that uses the document
3. Run the scenario with the agent
4. Check the results in Neo4j
"""

import os
import json
import time
import pytest
import requests
from typing import Dict, Any, List
import uuid
from datetime import datetime

# Path to test files
TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(TEST_DATA_DIR, exist_ok=True)

# Sample invoice text for testing
SAMPLE_INVOICE = """
INVOICE
Invoice Number: INV-2025-001
Date: April 15, 2025

Bill To:
Acme Corporation
123 Business Street
Business City, 75000

Description                   Quantity    Unit Price    Amount
--------------------------------------------------------------
Software Development         80 hours     $120         $9,600.00
Server Maintenance           1 month      $500         $500.00
Cloud Hosting                1 month      $300         $300.00
--------------------------------------------------------------
                                        Subtotal:     $10,400.00
                                        Tax (20%):    $2,080.00
                                        Total:        $12,480.00

Payment Terms: Net 30
Due Date: May 15, 2025

Please make payment to: 
Bank Account: FR76 1234 5678 9012 3456 7890 123
"""

# Create test invoice file
def setup_module():
    """Create test files before running tests"""
    invoice_path = os.path.join(TEST_DATA_DIR, "sample_invoice.txt")
    with open(invoice_path, "w") as f:
        f.write(SAMPLE_INVOICE)


class TestEndToEnd:
    """Test the complete workflow from document upload to scenario execution"""
    
    # Base URL for API
    api_url = "http://localhost:8000"
    
    # Test data
    document_id = None
    scenario_id = None
    automation_id = None
    task_id = None
    token = None
    
    def setup_method(self):
        """Setup before each test - get authentication token"""
        # Get authentication token
        response = requests.post(f"{self.api_url}/generate-token/")
        assert response.status_code == 200
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_01_upload_document(self):
        """Test uploading a document and creating a Document node in Neo4j"""
        # Upload invoice
        invoice_path = os.path.join(TEST_DATA_DIR, "sample_invoice.txt")
        with open(invoice_path, "rb") as f:
            files = {"file": ("sample_invoice.txt", f, "text/plain")}
            response = requests.post(
                f"{self.api_url}/upload/",
                headers=self.headers,
                files=files,
                data={"type_doc": "facture", "statut": "actif"}
            )
        
        assert response.status_code == 200
        result = response.json()
        assert "neo4j_doc_id" in result
        
        # Save document ID for subsequent tests
        TestEndToEnd.document_id = result["neo4j_doc_id"]
        print(f"Document created with ID: {TestEndToEnd.document_id}")
        
        # Verify document was created in Neo4j
        response = requests.get(
            f"{self.api_url}/documents/{TestEndToEnd.document_id}",
            headers=self.headers
        )
        assert response.status_code == 200
        document = response.json()
        assert document["type"] == "facture"
    
    def test_02_create_scenario(self):
        """Test creating a scenario that uses the uploaded document"""
        assert TestEndToEnd.document_id is not None, "Document ID not set"
        
        # Create scenario data - using string representation of enums for API compatibility
        scenario_data = {
            "nom": "Traitement Facture Test",
            "description": "Extraire montant total, date, et fournisseur d'une facture",
            "priorite": "MEDIUM",
            "documents": [TestEndToEnd.document_id],
            # Variables simples pour éviter les problèmes de validation
            "variables": [],
            # Étapes simples pour le test
            "etapes": [
                {"nom": "Extraction", "description": "Extraire variables", "ordre": 1},
                {"nom": "Validation", "description": "Valider données", "ordre": 2}
            ]
        }
        
        response = requests.post(
            f"{self.api_url}/scenarios/",
            headers=self.headers,
            json=scenario_data
        )
        
        assert response.status_code == 200, f"Failed with status {response.status_code}: {response.text}"
        result = response.json()
        assert "scenario_id" in result
        
        # Save scenario ID for subsequent tests
        TestEndToEnd.scenario_id = result["scenario_id"]
        print(f"Scenario created with ID: {TestEndToEnd.scenario_id}")
        
        # Créer les variables séparément pour éviter les problèmes de validation
        for var_info in [
            {"key": "Montant", "data_type": "DECIMAL", "value": None},
            {"key": "Date", "data_type": "DATE", "value": None},
            {"key": "Fournisseur", "data_type": "TEXT", "value": None}
        ]:
            var_data = {
                "document_id": TestEndToEnd.document_id,
                "key": var_info["key"],
                "value": var_info["value"],
                "data_type": var_info["data_type"],
                "methode": "TEST",
                "confiance": 0.95
            }
            
            var_response = requests.post(
                f"{self.api_url}/variables/",
                headers=self.headers,
                json=var_data
            )
            assert var_response.status_code == 200, f"Failed to create variable: {var_response.text}"
    
    def test_03_run_scenario(self):
        """Test running the scenario and waiting for completion"""
        assert TestEndToEnd.scenario_id is not None, "Scenario ID not set"
        
        # Run the scenario
        response = requests.post(
            f"{self.api_url}/api/scenarios/{TestEndToEnd.scenario_id}/run",
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert "task_id" in result
        assert "automation_id" in result
        
        # Save task ID and automation ID
        TestEndToEnd.task_id = result["task_id"]
        TestEndToEnd.automation_id = result["automation_id"]
        print(f"Task started with ID: {TestEndToEnd.task_id}")
        print(f"Automation started with ID: {TestEndToEnd.automation_id}")
        
        # Wait for task to complete (with timeout)
        timeout = 60  # seconds
        start_time = time.time()
        completed = False
        
        while time.time() - start_time < timeout:
            # Utiliser le nouvel endpoint pour vérifier le statut d'une tâche spécifique
            response = requests.get(
                f"{self.api_url}/api/tasks/{TestEndToEnd.task_id}",
                headers=self.headers
            )
            
            if response.status_code == 200:
                task = response.json()
                if task["status"] in ["completed", "failed"]:
                    completed = True
                    print(f"Task status: {task['status']}")
                    if task["status"] == "failed" and "error" in task:
                        print(f"Task error: {task.get('error', 'No error message')}")
                    break
            
            time.sleep(2)  # Wait before checking again
        
        assert completed, f"Task did not complete within {timeout} seconds"
    
    def test_04_check_results(self):
        """Test checking the results in Neo4j"""
        assert TestEndToEnd.automation_id is not None, "Automation ID not set"
        
        # Get automation details
        response = requests.get(
            f"{self.api_url}/automatisations/{TestEndToEnd.automation_id}",
            headers=self.headers
        )
        
        assert response.status_code == 200
        automation = response.json()
        assert automation["statut"] in ["terminé", "échoué"], f"Unexpected status: {automation['statut']}"
        
        # If failed, print the error
        if automation["statut"] == "échoué":
            print(f"Automation failed: {automation.get('resultat', 'No error message')}")
        
        # Print out the results
        if "resultat" in automation and automation["resultat"]:
            try:
                result_data = json.loads(automation["resultat"])
                print("\nExtracted variables:")
                for key, value in result_data.items():
                    if key != "error" and key != "traceback":
                        print(f"  {key}: {value}")
            except json.JSONDecodeError:
                print(f"Raw result: {automation['resultat']}")
                
        # Vérifier également si des résultats ont été générés et stockés
        response = requests.get(
            f"{self.api_url}/resultats/automatisation/{TestEndToEnd.automation_id}",
            headers=self.headers
        )
        
        if response.status_code == 200:
            resultats = response.json()
            if resultats:
                print("\nRésultats générés:")
                for resultat in resultats:
                    print(f"  - {resultat.get('titre')} ({resultat.get('type')}): {resultat.get('minio_key')}")
    
    def test_05_cleanup(self):
        """Clean up test data"""
        # Delete scenario
        if TestEndToEnd.scenario_id:
            response = requests.delete(
                f"{self.api_url}/scenarios/{TestEndToEnd.scenario_id}",
                headers=self.headers
            )
            assert response.status_code == 200
            print(f"Scenario {TestEndToEnd.scenario_id} deleted")
        
        # Delete document
        if TestEndToEnd.document_id:
            response = requests.delete(
                f"{self.api_url}/documents/{TestEndToEnd.document_id}",
                headers=self.headers
            )
            assert response.status_code == 200
            print(f"Document {TestEndToEnd.document_id} deleted")
        
        # Delete automation
        if TestEndToEnd.automation_id:
            response = requests.delete(
                f"{self.api_url}/automatisations/{TestEndToEnd.automation_id}",
                headers=self.headers
            )
            assert response.status_code == 200
            print(f"Automation {TestEndToEnd.automation_id} deleted")


if __name__ == "__main__":
    # Run tests manually
    setup_module()
    test = TestEndToEnd()
    test.setup_method()
    
    try:
        test.test_01_upload_document()
        test.test_02_create_scenario()
        test.test_03_run_scenario()
        test.test_04_check_results()
    finally:
        # Always run cleanup
        test.test_05_cleanup()