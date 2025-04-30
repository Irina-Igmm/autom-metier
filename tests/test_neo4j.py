"""
Tests unitaires pour le module Neo4j.
Utilise testcontainers pour simuler une base Neo4j temporaire.
"""

import os
import sys
import time
import uuid
import pytest
from testcontainers.neo4j import Neo4jContainer
from typing import Generator

# Ajout du répertoire principal au PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def neo4j_container() -> Generator[Neo4jContainer, None, None]:
    """
    Démarre un conteneur Neo4j temporaire pour les tests.

    Returns:
        Un conteneur Neo4j en cours d'exécution
    """
    # Utilisez l'image Neo4j officielle avec la version souhaitée
    container = Neo4jContainer("neo4j:5.13")
    container.start()

    # Attendre que le conteneur soit prêt
    time.sleep(2)

    yield container

    # Nettoyage
    container.stop()


@pytest.fixture(scope="module")
def neo4j_driver(neo4j_container):
    """
    Crée une instance du driver Neo4j connecté au conteneur de test.
    """
    from src.neo4j_driver import Neo4jDriver  # Import ici pour éviter l'initialisation globale
    uri = neo4j_container.get_connection_url()
    user = "neo4j"
    password = "password"
    driver = Neo4jDriver(
        uri=uri,
        user=user,
        password=password
    )
    driver.create_constraints()
    return driver


def test_create_document(neo4j_driver):
    """Test de création d'un document dans Neo4j."""
    # Arrange
    nom = "Document de test"
    type_doc = "test"
    chemin = "tests/document_test.pdf"

    # Act
    doc_id = neo4j_driver.create_document(
        nom=nom,
        type_doc=type_doc,
        chemin=chemin
    )

    # Assert
    assert doc_id is not None
    assert isinstance(doc_id, str)
    assert len(doc_id) > 0


def test_create_scenario(neo4j_driver):
    """Test de création d'un scénario."""
    # Arrange
    nom = "Scénario de test"
    description = "Description du scénario de test"
    priorite = "moyenne"

    # Act
    scenario_id = neo4j_driver.create_scenario(
        nom=nom,
        description=description,
        priorite=priorite
    )

    # Assert
    assert scenario_id is not None
    assert isinstance(scenario_id, str)
    assert len(scenario_id) > 0


def test_link_variable_to_document(neo4j_driver):
    """Test de liaison d'une variable à un document."""
    # Arrange
    doc_id = neo4j_driver.create_document(
        nom="Document avec variable",
        type_doc="facture",
        chemin="tests/facture_test.pdf"
    )
    variable_key = "montant"
    variable_value = 123.45
    variable_data_type = "number"
    # Act
    var_id = neo4j_driver.link_variable_to_document(
        document_id=doc_id,
        variable_nom=variable_key,
        variable_valeur=variable_value,
        variable_type=variable_data_type
    )
    # Assert
    assert var_id is not None
    assert isinstance(var_id, str)
    assert len(var_id) > 0


def test_start_and_update_automation(neo4j_driver):
    """Test de création et mise à jour d'une automatisation."""
    # Arrange
    scenario_id = neo4j_driver.create_scenario(
        nom="Scénario pour automatisation",
        description="Test d'automatisation",
        priorite="haute"
    )

    # Act - Démarrage de l'automatisation
    automation_id = neo4j_driver.start_automation(scenario_id)

    # Assert - L'automatisation a été créée
    assert automation_id is not None
    assert isinstance(automation_id, str)

    # Act - Mise à jour du statut
    neo4j_driver.update_automation_status(
        automation_id=automation_id,
        statut="terminé",
        resultat="Test réussi",
        duree=5
    )

    # Pas d'assertion directe, mais l'absence d'erreur indique le succès


def test_check_duplicate_invoice(neo4j_driver):
    """Test de vérification des doublons de facture."""
    # Arrange - Créer un document
    doc_id = neo4j_driver.create_document(
        nom="Facture test",
        type_doc="facture",
        chemin="tests/facture_doublons.pdf"
    )

    # Ajouter les variables numéro et fournisseur
    neo4j_driver.link_variable_to_document(
        document_id=doc_id,
        variable_nom="numeroFacture",
        variable_valeur="FACT-2025-001"
    )

    neo4j_driver.link_variable_to_document(
        document_id=doc_id,
        variable_nom="fournisseur",
        variable_valeur="FournisseurTest"
    )

    # Act & Assert - Pas de doublon si on exclut le document lui-même
    assert not neo4j_driver.check_duplicate_invoice(
        num_facture="FACT-2025-001",
        fournisseur="FournisseurTest",
        document_id=doc_id
    )

    # Act & Assert - Doublon si on n'exclut pas le document
    assert neo4j_driver.check_duplicate_invoice(
        num_facture="FACT-2025-001",
        fournisseur="FournisseurTest"
    )


def test_get_scenario_with_relations(neo4j_driver):
    """Test de récupération d'un scénario avec ses relations."""
    # Arrange
    # Créer un document
    doc_id = neo4j_driver.create_document(
        nom="Document pour relation",
        type_doc="test",
        chemin="tests/document_relation.pdf"
    )
    # Créer un scénario qui utilise ce document
    scenario_id = neo4j_driver.create_scenario(
        nom="Scénario avec relations",
        description="Test de relations",
        priorite="basse",
        document_ids=[doc_id],
        variables=[
            {"key": "var_test", "data_type": "string"}
        ]
    )
    # Act
    result = neo4j_driver.get_scenario_with_relations(scenario_id)
    # Assert
    assert result is not None
    assert "scenario" in result
    assert "documents" in result
    assert "variables" in result
    assert len(result["documents"]) == 1
    assert len(result["variables"]) == 1
    assert result["scenario"]["nom"] == "Scénario avec relations"


def test_context_manager(neo4j_container):
    """Test du context manager (__enter__, __exit__)."""
    from src.neo4j_driver import Neo4jDriver
    uri = neo4j_container.get_connection_url()
    
    # Context manager devrait établir la connexion et la fermer correctement
    with Neo4jDriver(uri=uri, user="neo4j", password="password") as driver:
        # Vérifier que la connexion est établie
        assert driver.driver is not None
        with driver.driver.session() as session:
            result = session.run("RETURN 1 as test")
            assert result.single()["test"] == 1
    
    # Vérifier que la connexion est fermée après le context manager
    assert driver.driver is None


def test_validate_uuid():
    """Test de la validation des UUIDs."""
    from src.neo4j_driver import Neo4jDriver
    driver = Neo4jDriver.__new__(Neo4jDriver)  # Instance sans initialiser
    
    # UUID valide
    valid_uuid = str(uuid.uuid4())
    driver.validate_uuid(valid_uuid)  # Ne devrait pas lever d'exception
    
    # UUID invalide
    with pytest.raises(ValueError):
        driver.validate_uuid("not-a-uuid")


def test_validate_variable():
    """Test de la validation des variables."""
    from src.neo4j_driver import Neo4jDriver
    driver = Neo4jDriver.__new__(Neo4jDriver)  # Instance sans initialiser
    
    # Variable valide
    valid_var = {"key": "test_key", "data_type": "string"}
    driver.validate_variable(valid_var)  # Ne devrait pas lever d'exception
    
    # Variables invalides
    with pytest.raises(ValueError):
        driver.validate_variable({"key": ""})  # Sans data_type
        
    with pytest.raises(ValueError):
        driver.validate_variable({"data_type": "string"})  # Sans key


def test_automation_with_agent_config(neo4j_driver):
    """Test de création d'automatisation avec agent_config."""
    # Arrange
    scenario_id = neo4j_driver.create_scenario(
        nom="Scénario pour agent config",
        description="Test agent_config",
        priorite="haute"
    )
    agent_config = {
        "model": "test-model",
        "temperature": 0.5,
        "max_tokens": 1000
    }
    
    # Act
    automation_id = neo4j_driver.start_automation(scenario_id, agent_config)
    
    # Assert
    with neo4j_driver.driver.session() as session:
        result = session.run(
            "MATCH (a:Automatisation {id: $id}) RETURN a",
            id=automation_id
        )
        record = result.single()
        assert record is not None
        automation = dict(record["a"])
        assert automation["statut"] == "queued"
        assert automation["agent_config"] == agent_config


def test_harmonized_status(neo4j_driver):
    """Test des statuts harmonisés dans l'automatisation."""
    # Arrange
    scenario_id = neo4j_driver.create_scenario(
        nom="Scénario pour statuts harmonisés",
        description="Test statuts",
        priorite="haute"
    )
    auto_id = neo4j_driver.start_automation(scenario_id)
    
    # Act - Mise à jour avec les anciens noms de statut
    neo4j_driver.update_automation_status(auto_id, "en cours")
    
    # Assert - Vérifier que le statut a été harmonisé en "running"
    with neo4j_driver.driver.session() as session:
        result = session.run(
            "MATCH (a:Automatisation {id: $id}) RETURN a.statut as statut",
            id=auto_id
        )
        assert result.single()["statut"] == "running"
    
    # Act - Mise à jour avec "terminé"
    neo4j_driver.update_automation_status(auto_id, "terminé")
    
    # Assert - Vérifier que le statut a été harmonisé en "success"
    with neo4j_driver.driver.session() as session:
        result = session.run(
            "MATCH (a:Automatisation {id: $id}) RETURN a.statut as statut",
            id=auto_id
        )
        assert result.single()["statut"] == "success"
