#!/usr/bin/env python3
"""
Script pour attendre que Neo4j soit disponible avant de lancer l'application principale.
Utilise la bibliothèque neo4j pour tenter d'établir une connexion.
"""

import sys
import time
import logging
import os
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables de configuration
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "30"))
RETRY_INTERVAL = int(os.getenv("RETRY_INTERVAL", "2"))


def is_neo4j_available():
    """Vérifie si Neo4j est disponible en tentant d'établir une connexion."""
    try:
        driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            # Exécuter une requête simple pour vérifier la connexion
            result = session.run("RETURN 1 as test")
            test_value = result.single()["test"]
            if test_value == 1:
                driver.close()
                return True
    except (ServiceUnavailable, AuthError) as e:
        logger.warning(f"Neo4j n'est pas encore disponible: {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la connexion à Neo4j: {e}")

    return False


def wait_for_neo4j():
    """Attend que Neo4j soit disponible."""
    logger.info(f"En attente de Neo4j sur {NEO4J_URI}...")

    for attempt in range(1, MAX_RETRIES + 1):
        if is_neo4j_available():
            logger.info("Neo4j est disponible!")
            return True

        logger.info(
            f"Tentative {attempt}/{MAX_RETRIES} - Neo4j n'est pas encore prêt. Nouvelle tentative dans {RETRY_INTERVAL} secondes...")
        time.sleep(RETRY_INTERVAL)

    logger.error(f"Neo4j n'est pas disponible après {MAX_RETRIES} tentatives.")
    return False


if __name__ == "__main__":
    if wait_for_neo4j():
        # Si Neo4j est disponible, exécuter la commande passée en arguments
        if len(sys.argv) > 1:
            import subprocess
            cmd = sys.argv[1:]
            logger.info(f"Lancement de la commande: {' '.join(cmd)}")
            subprocess.run(cmd)
            sys.exit(subprocess.returncode)
        sys.exit(0)
    else:
        sys.exit(1)
