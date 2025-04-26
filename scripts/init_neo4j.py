#!/usr/bin/env python3
"""
Script d'initialisation de Neo4j pour le système d'automatisation de scénarios métier.
Ce script:
1. Crée les contraintes d'unicité sur les nœuds
2. Insère des données de test (scénarios, documents, variables)
"""

import sys
import os
import random

# Ajout du répertoire parent au PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ""))

from src.neo4j_driver import Neo4jDriver
from src.config import config


def create_test_data(driver: Neo4jDriver):
    """
    Crée des données de test dans Neo4j.
    Inclut: 2 scénarios, 5 documents, 10 variables.
    """
    print("Création des données de test...")
    
    # Création de documents
    documents = [
        {
            "nom": "Facture Fournisseur A",
            "type": "facture",
            "chemin": "factures/2025/04/facture_fournA_123.pdf"
        },
        {
            "nom": "Contrat Maintenance",
            "type": "contrat",
            "chemin": "contrats/maintenance_2025.pdf"
        },
        {
            "nom": "Email de relance client",
            "type": "email",
            "chemin": "emails/relance_client_xyz.eml"
        },
        {
            "nom": "Fiche nouveau produit",
            "type": "produit",
            "chemin": "produits/nouveau_produit_abc.docx"
        },
        {
            "nom": "Devis projet",
            "type": "devis",
            "chemin": "devis/projet_xyz_2025.pdf"
        }
    ]
    
    document_ids = []
    for doc in documents:
        doc_id = driver.create_document(
            nom=doc["nom"],
            type_doc=doc["type"],
            chemin=doc["chemin"]
        )
        document_ids.append(doc_id)
        print(f"Document créé: {doc['nom']} (ID: {doc_id})")
    
    # Création de variables liées aux documents
    variables = [
        {"document_index": 0, "nom": "numeroFacture", "valeur": "FACT-2025-123", "type": "string"},
        {"document_index": 0, "nom": "fournisseur", "valeur": "Fournisseur A", "type": "string"},
        {"document_index": 0, "nom": "montantHT", "valeur": 1500.50, "type": "number"},
        {"document_index": 0, "nom": "dateEmission", "valeur": "2025-04-15", "type": "date"},
        
        {"document_index": 1, "nom": "dateFinContrat", "valeur": "2026-12-31", "type": "date"},
        {"document_index": 1, "nom": "prestataire", "valeur": "Maintenance Pro", "type": "string"},
        
        {"document_index": 2, "nom": "client", "valeur": "Client XYZ", "type": "string"},
        {"document_index": 2, "nom": "montantDu", "valeur": 2750.00, "type": "number"},
        
        {"document_index": 3, "nom": "nomProduit", "valeur": "Produit ABC", "type": "string"},
        {"document_index": 3, "nom": "categorie", "valeur": "Électronique", "type": "string"}
    ]
    
    for var in variables:
        confiance = round(random.uniform(0.85, 0.99), 2)
        var_id = driver.link_variable_to_document(
            document_id=document_ids[var["document_index"]],
            variable_nom=var["nom"],
            variable_valeur=var["valeur"],
            variable_type=var["type"],
            confiance=confiance
        )
        print(f"Variable créée: {var['nom']} = {var['valeur']} (ID: {var_id})")
    
    # Création de scénarios
    scenario1_vars = [
        {"nom": "nomClient", "type": "string"},
        {"nom": "emailClient", "type": "string"},
        {"nom": "dateFin", "type": "date"}
    ]
    
    scenario1_id = driver.create_scenario(
        nom="Fin de contrat fournisseur",
        description="Génération d'un email de notification 30 jours avant la fin d'un contrat fournisseur",
        priorite="haute",
        document_ids=[document_ids[1]],  # Contrat Maintenance
        variables=scenario1_vars
    )
    print(f"Scénario créé: Fin de contrat fournisseur (ID: {scenario1_id})")
    
    scenario2_vars = [
        {"nom": "email", "type": "string"},
        {"nom": "objet", "type": "string"},
        {"nom": "corps", "type": "string"}
    ]
    
    scenario2_id = driver.create_scenario(
        nom="Relance impayé",
        description="Détection d'un impayé et génération automatique d'un email de relance",
        priorite="moyenne",
        document_ids=[document_ids[0], document_ids[2]],  # Facture et Email de relance
        variables=scenario2_vars
    )
    print(f"Scénario créé: Relance impayé (ID: {scenario2_id})")
    
    # Création d'une automatisation terminée
    automation_id = driver.start_automation(scenario1_id)
    
    # Simuler une exécution réussie
    driver.update_automation_status(
        automation_id=automation_id,
        statut="terminé",
        resultat="Email de notification généré avec succès",
        duree=12
    )
    print(f"Automatisation créée pour scénario 1 (ID: {automation_id})")
    
    # Création d'une automatisation en cours
    automation_id2 = driver.start_automation(scenario2_id)
    print(f"Automatisation en cours créée pour scénario 2 (ID: {automation_id2})")
    
    print("Données de test créées avec succès!")


def main():
    """Fonction principale d'initialisation de Neo4j"""
    try:
        # Connexion à Neo4j
        print("Connexion à Neo4j...")
        driver = Neo4jDriver(
            uri=config.NEO4J_URI,
            user=config.NEO4J_USER,
            password=config.NEO4J_PASSWORD
        )
        
        # Création des contraintes d'unicité
        print("Création des contraintes...")
        driver.create_constraints()
        
        # Création des données de test
        create_test_data(driver)
        
        print("Initialisation de Neo4j terminée avec succès!")
        
    except Exception as e:
        print(f"Erreur lors de l'initialisation de Neo4j: {e}")
    finally:
        if 'driver' in locals():
            driver.close()


if __name__ == "__main__":
    main()