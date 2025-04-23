# Jalons pour la mise en place du système d’automatisation de scénarios métier

## Jalon 1 : Configuration de l’environnement et initialisation du projet
**Objectif** : Mettre en place la structure du projet, configurer l’environnement de développement, et initialiser le dépôt GitHub.

**Durée estimée** : 2 jours

**Tâches** :
1. Créer un dépôt GitHub avec une structure claire :
   - `/src` : Code source (FastAPI, agent IA, intégrations).
   - `/tests` : Tests unitaires et intégration.
   - `/docs` : Documentation technique.
   - `/scripts` : Scripts utilitaires (ex. : initialisation Neo4j).
2. Configurer les fichiers de base :
   - `.gitignore` (exclure `.env`, `*.pyc`, etc.).
   - `.env.example` pour variables d’environnement (Neo4j, MinIO, Groq API).
   - `requirements.txt` pour dépendances Python (`fastapi`, `neo4j`, `minio`, `langchain`, etc.).
3. Rédiger un `README.md` initial avec :
   - Description du projet.
   - Instructions pour cloner et configurer localement.
4. Initialiser un environnement virtuel Python et installer les dépendances.

**Livrables** :
- Dépôt GitHub public avec structure initiale.
- Fichiers `.gitignore`, `.env.example`, `requirements.txt`.
- `README.md` avec instructions de base.

**Critères de validation** :
- Le dépôt est accessible et bien structuré.
- Les dépendances s’installent sans erreur via `pip install -r requirements.txt`.
- Le `README.md` est clair et contient les instructions initiales.

---

## Jalon 2 : Configuration de l’infrastructure via Docker
**Objectif** : Configurer les services FastAPI, Neo4j, et MinIO avec Docker pour un environnement reproductible.

**Durée estimée** : 3 jours

**Tâches** :
1. Créer un `Dockerfile` pour l’application FastAPI :
   - Base : `python:3.11-slim`.
   - Installation des dépendances via `requirements.txt`.
   - Exposition du port 8000.
2. Créer un `docker-compose.yml` pour orchestrer :
   - Service FastAPI (port 8000).
   - Service Neo4j (ports 7474, 7687).
   - Service MinIO (port 9000, console 9001).
3. Configurer les variables d’environnement dans `.env` pour :
   - Connexion Neo4j (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`).
   - Connexion MinIO (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_ENDPOINT`).
   - Clé API Groq (`GROQ_API_KEY`).
4. Tester le démarrage des services avec `docker-compose up --build`.
5. Documenter les instructions de démarrage dans le `README.md`.

**Livrables** :
- `Dockerfile` pour FastAPI.
- `docker-compose.yml` fonctionnel.
- `.env.example` mis à jour.
- Section “Démarrage avec Docker” dans `README.md`.

**Critères de validation** :
- Les services démarrent sans erreur via `docker-compose up --build`.
- Neo4j est accessible via navigateur (http://localhost:7474).
- MinIO est accessible via console (http://localhost:9001).
- FastAPI répond sur http://localhost:8000.

---

## Jalon 3 : Modélisation et configuration de Neo4j
**Objectif** : Modéliser les entités (Document, Variable, Scénario, Automatisation) dans Neo4j et implémenter les requêtes Cypher de base.

**Durée estimée** : 3 jours

**Tâches** :
1. Définir le schéma des nœuds et relations :
   - Nœuds : `Document`, `Variable`, `Scénario`, `Automatisation`.
   - Relations : `UTILISE`, `GÉNÈRE`, `LIÉE_À`.
2. Implémenter un script Python (`/scripts/init_neo4j.py`) pour :
   - Créer des contraintes d’unicité (ex. : `:Document(id)`).
   - Insérer des données de test (ex. : 2 scénarios, 5 documents, 10 variables).
3. Écrire des requêtes Cypher pour :
   - Créer un scénario avec documents et variables.
   - Vérifier les doublons (ex. : factures).
   - Récupérer un scénario avec ses relations.
4. Intégrer la bibliothèque `neo4j` dans `/src/neo4j_driver.py` pour gérer les connexions et requêtes.
5. Documenter le schéma et les requêtes dans `/docs/neo4j_schema.md`.

**Livrables** :
- Script `/scripts/init_neo4j.py` pour initialisation.
- Module `/src/neo4j_driver.py` avec fonctions Cypher.
- Documentation `/docs/neo4j_schema.md` avec schéma visuel et requêtes.
- Données de test insérées dans Neo4j.

**Critères de validation** :
- Le schéma Neo4j est cohérent avec les spécifications.
- Les requêtes Cypher sont optimisées et fonctionnelles.
- Les données de test sont accessibles via Neo4j Browser.
- Le module `neo4j_driver.py` gère les connexions sans erreur.

---

## Jalon 4 : Implémentation des endpoints FastAPI
**Objectif** : Développer les endpoints REST FastAPI avec BackgroundTasks pour la gestion des scénarios.

**Durée estimée** : 4 jours

**Tâches** :
1. Créer la structure FastAPI dans `/src/main.py` :
   - Initialisation de l’app FastAPI.
   - Configuration de la dépendance Neo4j.
2. Implémenter les endpoints :
   - `POST /scenarios/` : Crée un scénario et ses relations dans Neo4j.
   - `POST /scenarios/{id}/run` : Lance une tâche asynchrone pour exécuter un scénario.
3. Configurer **BackgroundTasks** dans `/src/tasks.py` pour :
   - Télécharger un document depuis MinIO.
   - Appeler l’agent IA (stub temporaire).
   - Mettre à jour Neo4j.
4. Intégrer la bibliothèque `minio-py` dans `/src/minio_client.py` pour gérer les uploads/downloads.
5. Ajouter une gestion basique des erreurs (timeouts, exceptions).
6. Documenter les endpoints dans `/docs/api.md` avec exemples de payloads.

**Livrables** :
- `/src/main.py` avec endpoints FastAPI.
- `/src/tasks.py` avec logique BackgroundTasks.
- `/src/minio_client.py` pour MinIO.
- Documentation `/docs/api.md` avec spécifications OpenAPI.

**Critères de validation** :
- Les endpoints répondent correctement (test via `curl` ou Postman).
- Les tâches asynchrones s’exécutent sans bloquer l’API.
- Les documents sont téléchargés depuis MinIO.
- Les mises à jour Neo4j sont visibles dans la base.

---

## Jalon 5 : Configuration et intégration de l’agent IA
**Objectif** : Implémenter l’agent IA multi-outils avec LangChain et Groq Cloud pour orchestrer les tâches des scénarios.

**Durée estimée** : 5 jours

**Tâches** :
1. Configurer LangChain dans `/src/agent.py` :
   - Initialiser un agent avec Groq Cloud (modèle : justifier le choix, ex. : `mixtral-8x7b` pour coût/latence).
   - Activer RAG pour indexation des documents via LlamaIndex.
2. Définir les outils pour chaque tâche :
   - Extraction de variables : Appel Groq avec prompt structuré.
   - Génération de templates : Jinja2 pour HTML ou Google Docs API.
   - Soumission web : Playwright pour navigation automatisée.
3. Intégrer les outils dans l’agent via LangChain (`Tool` objects).
4. Implémenter la logique dans `/src/tasks.py` pour :
   - Télécharger un document depuis MinIO.
   - Extraire/générer des variables via l’agent.
   - Remplir un template ou soumettre un formulaire.
   - Uploader le résultat sur MinIO.
   - Mettre à jour Neo4j.
5. Justifier le choix de Groq dans `/docs/ia_justification.md` (coût, latence, confidentialité).
6. Tester l’agent sur un scénario simple (ex. : extraction de variables d’une facture).

**Livrables** :
- `/src/agent.py` avec configuration LangChain.
- Outils définis pour extraction, génération, sou **Critères de validation** :
- L’agent extrait correctement les variables d’un document.
- Les templates sont générés et stockés dans MinIO.
- Les formulaires web sont soumis via Playwright.
- Les mises à jour Neo4j reflètent les résultats.
- La documentation `/docs/ia_justification.md` est complète.

---

## Jalon 6 : Tests unitaires et intégration
**Objectif** : Mettre en place des tests unitaires et d’intégration pour garantir la robustesse du système.

**Durée estimée** : 3 jours

**Tâches** :
1. Configurer Pytest dans `/tests` :
   - Tests unitaires pour les endpoints FastAPI (`/tests/test_api.py`).
   - Tests pour les fonctions Neo4j (`/tests/test_neo4j.py`).
   - Tests pour les interactions MinIO (`/tests/test_minio.py`).
2. Utiliser `testcontainers` pour simuler Neo4j dans les tests.
3. Configurer un serveur MinIO temporaire pour les tests (`minio-server --dev`).
4. Tester les scénarios complets (ex. : création et exécution d’un scénario).
5. Documenter les instructions de test dans `/docs/testing.md`.

**Livrables** :
- Répertoire `/tests` avec scripts Pytest.
- Documentation `/docs/testing.md`.
- Rapport de couverture des tests.

**Critères de validation** :
- Les tests unitaires passent sans erreur (`pytest`).
- Les tests d’intégration simulent correctement Neo4j et MinIO.
- La couverture des tests inclut tous les endpoints et tâches clés.

---

## Jalon 7 : Configuration pour Google Colab
**Objectif** : Adapter le projet pour une exécution sur Google Colab sans GPU.

**Durée estimée** : 2 jours

**Tâches** :
1. Créer un notebook Colab partitionné dans `/docs/colab_notebook.ipynb` :
   - Section 1 : Configuration (installation des dépendances, variables d’environnement).
   - Section 2 : Initialisation (Neo4j, MinIO via conteneurs cloud).
   - Section 3 : Exécution d’un scénario (ex. : relance impayé).
   - Section 4 : Tests simplifiés.
2. Tester l’exécution pas à pas dans Colab.
3. Documenter les limitations (ex. : Playwright peut nécessiter des ajustements).

**Livrables** :
- Notebook `/docs/colab_notebook.ipynb`.
- Section “Exécution sur Colab” dans `README.md`.

**Critères de validation** :
- Le notebook s’exécute sans erreur dans Colab.
- Un scénario complet est exécuté avec succès.
- Les instructions sont claires pour les utilisateurs.

---

## Jalon 8 : Finalisation et soumission
**Objectif** : Finaliser la documentation, valider l’ensemble du système, et soumettre le projet.

**Durée estimée** : 2 jours

**Tâches** :
1. Finaliser le `README.md` avec :
   - Instructions complètes pour local et Colab.
   - Schéma d’architecture.
   - Guide de mise en production.
2. Compléter la documentation technique dans `/docs` :
   - `/docs/architecture.md`.
   - `/docs/api.md`.
   - `/docs/neo4j_schema.md`.
   - `/docs/ia_justification.md`.
   - `/docs/testing.md`.
3. Vérifier la conformité du code (PEP8, docstrings, commentaires).
4. Tester l’ensemble du système avec `docker-compose up --build`.
5. Pousser le code final sur GitHub et vérifier le lien.

**Livrables** :
- Dépôt GitHub complet et fonctionnel.
- Documentation finale dans `/docs` et `README.md`.
- Lien GitHub soumis.

**Critères de validation** :
- Le système est entièrement fonctionnel (tous les scénarios s’exécutent).
- La documentation est claire, complète, et respecte les spécifications.
- Le dépôt passe les vérifications (Docker, tests, PEP8).

---

## Rés