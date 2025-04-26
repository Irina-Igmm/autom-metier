# Roadmap pour la mise en place du système d'automatisation de scénarios métier

Cette roadmap détaille les étapes nécessaires pour concevoir, implémenter et soumettre le projet d'automatisation de scénarios métier piloté par des agents IA, tel que décrit dans le document de test.

---

## Phase 1 : Compréhension et Planification

1. **Analyse des exigences**
   - Relire le document pour identifier les spécifications clés : création et exécution de scénarios, gestion des documents, extraction de variables, génération de contenu.
   - Lister les cas d'usage : fin de contrat fournisseur, réception de facture, relance d'impayé, ajout de produit.

2. **Choix des technologies**
   - Utiliser FastAPI (API REST), Neo4j (graphe), MinIO (stockage), et un LLM (e.g., GPT-3.5, Llama-2).
   - Choisir un modèle IA en fonction du coût, de la latence et de la confidentialité. Justifier ce choix dans la documentation.
   - Opter pour LangChain ou LlamaIndex pour orchestrer les appels au LLM.

3. **Définition de l'architecture**
   - Dessiner un schéma : Client → FastAPI → Neo4j/MinIO ↔ Agent IA.
   - Planifier les nœuds Neo4j : `Document`, `Variable`, `Scenario`, `Automatisation`, avec leurs relations.

---

## Phase 2 : Configuration de l'environnement de développement

1. **Installation des prérequis**
   - Installer Docker et docker-compose.
   - Installer Python 3.x et créer un environnement virtuel.

2. **Configuration de docker-compose**
   - Créer un `docker-compose.yml` pour orchestrer FastAPI, Neo4j, et MinIO.
   - Définir les variables d’environnement (e.g., ports, mots de passe).

3. **Initialisation du projet**
   - Créer un repository GitHub avec la structure : `src/`, `tests/`, `infra/`, `docs/`.
   - Ajouter un fichier `requirements.txt` avec les dépendances (fastapi, neo4j-driver, minio, etc.).

---

## Phase 3 : Développement de l'API FastAPI

1. **Modélisation des entités**
   - Définir des modèles Pydantic pour `Document`, `Variable`, `Scenario`, et `Automatisation`.
   - Créer des schémas pour les requêtes et réponses API.

2. **Implémentation des endpoints**
   - `POST /scenarios/` : Crée un scénario et le stocke dans Neo4j.
   - `POST /scenarios/{id}/run` : Lance l'exécution asynchrone avec `BackgroundTasks`.

3. **Intégration avec Neo4j**
   - Connecter FastAPI à Neo4j via `neo4j-driver`.
   - Écrire des requêtes Cypher pour insérer et mettre à jour les nœuds/relations.

4. **Intégration avec MinIO**
   - Utiliser `minio-py` pour uploader/downloader les documents.
   - Stocker les métadonnées dans Neo4j.

---

## Phase 4 : Développement de l'agent IA

1. **Choix et configuration du LLM**
   - Sélectionner un modèle (e.g., Llama-2) et configurer l’accès (API ou local).
   - Documenter la justification (e.g., open-source, performance).

2. **Orchestration avec LangChain**
   - Créer des chaînes pour appeler le LLM et les outils (extraction, génération).
   - Configurer un agent multi-outils.

3. **Implémentation des outils**
   - Développer des fonctions Python pour :
     - Extraire des variables (e.g., montant, fournisseur) d’un document.
     - Générer un email ou remplir un template.
   - Intégrer ces outils à l’agent IA.

4. **Gestion des templates**
   - Utiliser Google Docs API ou HTML pour remplir les templates avec les variables extraites.

---

## Phase 5 : Intégration et Tests

1. **Tests unitaires**
   - Écrire des tests Pytest pour les endpoints FastAPI.
   - Tester les interactions avec Neo4j et MinIO.

2. **Tests d'intégration**
   - Simuler les cas d’usage avec des données fictives.
   - Vérifier l’exécution complète d’un scénario.

3. **Tests de l'agent IA**
   - Tester l’extraction de variables et la génération de contenu sur des documents échantillons.

---

## Phase 6 : Documentation et Finalisation

1. **Rédaction de la documentation**
   - README : Instructions pour lancer le projet (docker-compose up, dépendances).
   - Document technique : Architecture, choix du LLM, justifications.

2. **Préparation pour la mise en production**
   - Tester le `Dockerfile` et `docker-compose.yml`.
   - Documenter les variables d’environnement.

3. **Revue du code**
   - Vérifier la conformité PEP8.
   - Ajouter des commentaires et docstrings.

---

## Phase 7 : Soumission

1. **Hébergement sur GitHub**
   - Pousser le code sur GitHub avec une structure propre.

2. **Envoi de la documentation**
   - Fournir un fichier Markdown avec la documentation technique.

3. **Vérification finale**
   - Lancer `docker-compose up --build` pour tester le système.
   - Confirmer que tous les livrables sont inclus.

---

### Conseils supplémentaires
- Prioriser la modularité et la lisibilité du code.
- Justifier chaque choix technique dans la documentation.
- Tester régulièrement avec `docker-compose` pour éviter les erreurs de dernière minute.

Bonne chance dans la réalisation de ce projet !