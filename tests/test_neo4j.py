# tests/test_neo4j_driver.py
"""
Tests unitaires pour le module Neo4jDriver.
Utilise testcontainers pour simuler une base Neo4j temporaire.
"""
import os
import sys
import time
import uuid
import pytest
from testcontainers.neo4j import Neo4jContainer
from src.neo4j_driver import Neo4jDriver

# Ajouter le répertoire src au PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture(scope="module")
def neo4j_container():
    """
    Démarre un conteneur Neo4j temporaire pour les tests.
    """
    container = Neo4jContainer("neo4j:5.19").with_env("NEO4J_AUTH", "neo4j/test2025*7")
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="module")
def neo4j_driver(neo4j_container):
    """
    Crée une instance du driver Neo4j connecté au conteneur de test.
    """
    uri = neo4j_container.get_connection_url()
    driver = Neo4jDriver(uri=uri, user="neo4j", password="test2025*7")
    # créer les contraintes dans la base de test
    driver._create_constraints()
    return driver


def test_create_document(neo4j_driver):
    """Test de création d'un document dans Neo4j."""
    doc_id = neo4j_driver.create_document("Test Document", "test", "dummy_key")
    assert doc_id is not None


def test_create_scenario(neo4j_driver):
    """Test de création d'un scénario sans dépendances."""
    scenario_id = neo4j_driver.create_scenario("Test Scenario", "", "moyenne")
    assert scenario_id is not None


def test_link_variable_to_document(neo4j_driver):
    """Test de liaison d'une variable à un document."""
    doc_id = neo4j_driver.create_document(
        titre="DocVar",
        type="test",
        minio_key="key"
    )
    var_id = neo4j_driver.link_variable_to_document(
        document_id=doc_id,
        variable_nom="montant",
        variable_valeur=100,
        variable_type="float"
    )
    assert var_id and isinstance(var_id, str)


def test_start_and_update_automation(neo4j_driver):
    """Test de création et mise à jour d'une automatisation."""
    scenario_id = neo4j_driver.create_scenario(
        nom="AutoTest",
        description="",
        priorite="basse"
    )
    auto_id = neo4j_driver.start_automation(scenario_id, agent_config={})
    assert auto_id and isinstance(auto_id, str)
    # mise à jour du statut
    neo4j_driver.update_automation_status(
        automation_id=auto_id,
        statut="terminé",
        resultat="OK",
        duree_ms=10
    )


def test_check_duplicate_invoice(neo4j_driver):
    """Test de détection de doublon de facture."""
    doc_id = neo4j_driver.create_document(
        titre="FactTest",
        type="facture",
        minio_key="key"
    )
    # ajouter numéro et fournisseur
    neo4j_driver.link_variable_to_document(
        document_id=doc_id,
        variable_nom="numeroFacture",
        variable_valeur="INV-1",
        variable_type="string"
    )
    neo4j_driver.link_variable_to_document(
        document_id=doc_id,
        variable_nom="fournisseur",
        variable_valeur="Fourn",
        variable_type="string"
    )
    assert not neo4j_driver.check_duplicate_invoice(
        num_facture="INV-1",
        fournisseur="Fourn",
        document_id=doc_id
    )
    assert neo4j_driver.check_duplicate_invoice(
        num_facture="INV-1",
        fournisseur="Fourn"
    )


def test_get_scenario_with_relations(neo4j_driver):
    """Test de récupération d'un scénario avec ses documents et variables."""
    doc_id = neo4j_driver.create_document(
        titre="DocRel",
        type="test",
        minio_key="key"
    )
    scenario_id = neo4j_driver.create_scenario(
        nom="RelTest",
        description="",
        priorite="haute",
        document_ids=[doc_id],
        variables=[{"key": "k", "data_type": "string"}]
    )
    res = neo4j_driver.get_scenario_with_relations(scenario_id)
    assert res and "scenario" in res
    assert res["documents"] and res["variables"]


def test_context_manager(neo4j_container):
    """Test du context manager (__enter__/__exit__)."""
    uri = neo4j_container.get_connection_url()
    with Neo4jDriver(uri=uri, user="neo4j", password="test2025*7") as drv:
        assert drv.driver is not None
    assert drv.driver is None


def test_find_and_delete_entity(neo4j_driver):
    """Test de find_entities et delete_entity."""
    label = "TestNode"
    props = {"id": str(uuid.uuid4()), "foo": "bar"}
    node_id = neo4j_driver.create_node(label, props)
    found = neo4j_driver.find_entities(label, {"foo": "bar"})
    assert any(n["id"] == node_id for n in found)
    neo4j_driver.delete_entity(label, node_id)
    found2 = neo4j_driver.find_entities(label, {"foo": "bar"})
    assert all(n["id"] != node_id for n in found2)
