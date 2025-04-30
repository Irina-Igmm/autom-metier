#!/usr/bin/env python3
"""
Script d'initialisation de Neo4j pour le système d'automatisation de scénarios métier.
Ce script:
1. Crée les contraintes d'unicité sur les nœuds
2. Insère des données de test (scénarios, documents, variables, automatisations)
"""
import os
import sys
# Ajouter le dossier parent au PYTHONPATH pour pouvoir importer `src`
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import random
from src.config import config
from src.models import Document, Variable, Scenario, DataType
from src.neo4j_driver import Neo4jDriver
import uuid


def create_test_data(driver: Neo4jDriver):
    """
    Création de données de test dans Neo4j pour les documents, variables et scénarios.
    """

    print("Création des données de test...")

    # 1. Création de documents via Document model
    documents = [
        {"nom": "Facture Fournisseur A", "type": "facture",
            "chemin": "factures/2025/04/facture_fournA_123.pdf"},
        {"nom": "Contrat Maintenance",    "type": "contrat",
            "chemin": "contrats/maintenance_2025.pdf"},
        {"nom": "Email relance client",   "type": "email",
            "chemin": "emails/relance_client_xyz.eml"},
        {"nom": "Fiche produit ABC",      "type": "produit",
            "chemin": "produits/nouveau_produit_abc.docx"},
        {"nom": "Devis Projet XYZ",       "type": "devis",
            "chemin": "devis/projet_xyz_2025.pdf"},
    ]
    document_ids = []
    for info in documents:
        # instantiate Document model
        doc_model = Document(
            id=str(uuid.uuid4()),
            titre=info["nom"],
            type=info["type"],
            minio_key=info["chemin"]
        )
        doc_id = driver.create_document(
            titre=doc_model.titre,
            type=doc_model.type,
            minio_key=doc_model.minio_key,
            statut=doc_model.statut.value,
        )
        document_ids.append(doc_id)
        print(f"Document créé: {info['nom']} (ID: {doc_id})")

    # 2. Variables liées aux documents
    vars_to_link = [
        {"doc_idx": 0, "key": "numeroFacture",
            "value": "FACT-2025-123", "variable_type": "string"},
        {"doc_idx": 0, "key": "fournisseur",
            "value": "Fournisseur A",    "variable_type": "string"},
        {"doc_idx": 0, "key": "montantHT",
            "value": 1500.50,           "variable_type": "float"},
        {"doc_idx": 0, "key": "dateEmission",
            "value": "2025-04-15",      "variable_type": "date"},
        {"doc_idx": 1, "key": "dateFinContrat",
            "value": "2026-12-31",      "variable_type": "date"},
        {"doc_idx": 1, "key": "prestataire",
            "value": "Maintenance Pro",  "variable_type": "string"},
        {"doc_idx": 2, "key": "client",
            "value": "Client XYZ",       "variable_type": "string"},
        {"doc_idx": 2, "key": "montantDu",
            "value": 2750.00,           "variable_type": "float"},
        {"doc_idx": 3, "key": "nomProduit",
            "value": "Produit ABC",      "variable_type": "string"},
        {"doc_idx": 3, "key": "categorie",
            "value": "Électronique",     "variable_type": "string"},
    ]
    for v in vars_to_link:
        conf = round(random.uniform(0.8, 0.99), 2)
        # use Variable model
        var_model = Variable(
            key=v["key"], data_type=v["variable_type"], value=str(v["value"]), confiance=conf
        )
        var_id = driver.link_variable_to_document(
            document_id=document_ids[v["doc_idx"]],
            variable_nom=var_model.key,
            variable_valeur=var_model.value,
            variable_type=var_model.data_type.value,
            confiance=var_model.confiance,
        )
        print(
            f"  • Variable créée: {v['key']}={v['value']} (ID={var_id}, conf={conf})")

    # 3. Scénarios
    # Variables de scénario via Pydantic Variable et DataType
    scen1_vars = [
        Variable(key="nomClient", data_type=DataType.STRING,
                 value=None, confiance=None),
        Variable(key="emailClient", data_type=DataType.STRING,
                 value=None, confiance=None),
        Variable(key="dateFin", data_type=DataType.DATE,
                 value=None, confiance=None),
    ]
    # Création de scénario via Scenario model
    scen1_model = Scenario(
        nom="Fin de contrat fournisseur",
        description="Notification 30j avant fin contrat",
        priorite="haute",
        documents=[document_ids[1]],
        variables=[var.key for var in scen1_vars],
        etapes=[]
    )
    scen1_id = driver.create_scenario(
        nom=scen1_model.nom,
        description=scen1_model.description,
        priorite=scen1_model.priorite.value,
        document_ids=scen1_model.documents,
        variables=[{"key": var.key, "data_type": var.data_type.value}
                   for var in scen1_vars]
    )
    print(f"  • Scénario créé: Fin de contrat (ID={scen1_id})")

    scen2_vars = [
        Variable(key="email", data_type=DataType.STRING,
                 value=None, confiance=None),
        Variable(key="objet", data_type=DataType.STRING,
                 value=None, confiance=None),
        Variable(key="corps", data_type=DataType.STRING,
                 value=None, confiance=None),
    ]
    scen2_model = Scenario(
        nom="Relance impayé",
        description="Détecte impayé et envoie email",
        priorite="moyenne",
        documents=[document_ids[0], document_ids[2]],
        variables=[var.key for var in scen2_vars],
        etapes=[]
    )
    scen2_id = driver.create_scenario(
        nom=scen2_model.nom,
        description=scen2_model.description,
        priorite=scen2_model.priorite.value,
        document_ids=scen2_model.documents,
        variables=[{"key": var.key, "data_type": var.data_type.value}
                   for var in scen2_vars]
    )
    print(f"  • Scénario créé: Relance impayé (ID={scen2_id})")

    # 4. Automatisations
    auto1_cfg = {"model": "llama-4-scout",
                 "prompt_template": "notif_template", "temperature": 0.3}
    auto1 = driver.start_automation(scen1_id, agent_config=auto1_cfg)
    driver.update_automation_status(
        auto1, statut="success", resultat="OK", duree_ms=25)
    print(f"  • Automatisation réussie (ID={auto1})")

    auto2_cfg = {"model": "mixtral",
                 "prompt_template": "reminder_tpl", "temperature": 0.7}
    auto2 = driver.start_automation(scen2_id, agent_config=auto2_cfg)
    # reste en 'queued'
    print(f"  • Automatisation queued (ID={auto2})")

    print("✅ Données de test Neo4j créées.")


def main():
    try:
        print("➤ Connexion à Neo4j…")
        drv = Neo4jDriver(uri=config.NEO4J_URI,
                          user=config.NEO4J_USER, password=config.NEO4J_PASSWORD)
        print("➤ Création des contraintes…")
        drv._create_constraints()
        create_test_data(drv)
    except Exception as e:
        print(f"‼️ Erreur init Neo4j: {e}")
    finally:
        if 'drv' in locals() and drv:
            drv.close()


if __name__ == "__main__":
    main()
