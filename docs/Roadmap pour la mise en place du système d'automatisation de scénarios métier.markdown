# Roadmap pour la mise en place du système d'automatisation de scénarios métier

Ce roadmap intègre les exigences de fonctionnalités et d'entités spécifiées dans le "Document de Test – AI Engineer.pdf". Il est organisé en phases logiques pour guider la conception, l'implémentation et la soumission du projet.

---

## Phase 1 : Compréhension et Planification

1. **Analyse des exigences fonctionnelles et entités**
   - Identifier les entités clés :
     - **Document** : Fichier stocké dans MinIO avec métadonnées (ID, type, date, minio_key).
     - **Variable** : Attribut extrait d'un document (ex. : numéro de facture, fournisseur, montant).
     - **Scénario** : Enchaînement d'étapes métier (ex. : création, validation, envoi).
     - **Automatisation** : Configuration d'un agent IA pour exécuter un scénario.
   - Lister les fonctionnalités principales :
     - Création de scénarios via API.
     - Exécution automatisée des scénarios avec extraction de variables et traitement des documents.
     - Stockage et gestion des documents dans MinIO.
     - Gestion des relations entre entités dans Neo4j.

2. **Choix des technologies**
   - Confirmer l'utilisation de **FastAPI**, **Neo4j**, **MinIO**, et un **LLM** (ex. : GPT-3.5, Llama-2).
   - Sélectionner un framework pour l'agent IA (ex. : LangChain).

3. **Définition de l'architecture**
   - Modéliser les relations entre entités dans Neo4j (ex. : Document → Variable, Scénario → Document).
   - Planifier le flux : Création de scénario → Stockage dans Neo4j → Exécution via agent IA → Mise à jour des données.

---

## Phase 2 : Configuration de l'environnement et Modélisation des Entités

1. **Installation des prérequis**
   - Installer Docker, Python 3.x, et créer un environnement virtuel.

2. **Configuration de docker-compose**
   - Créer `docker-compose.yml` pour FastAPI, Neo4j, MinIO.
   - Définir les variables d'environnement pour chaque service.

3. **Modélisation des entités**
   - Définir des modèles Pydantic pour **Document**, **Variable**, **Scénario**, et **Automatisation**.
   - Assurer que les modèles incluent les attributs requis (ex. : minio_key pour Document).

---

## Phase 3 : Développement de l'API et Gestion des Entités

1. **Implémentation des endpoints FastAPI**
   - `POST /scenarios/` : Créer un scénario et le stocker dans Neo4j avec liens vers Document et Variable.
   - `POST /scenarios/{id}/run` : Exécuter un scénario de manière asynchrone avec `BackgroundTasks`.

2. **Gestion des documents dans MinIO**
   - Implémenter l'upload et le téléchargement des documents via MinIO.
   - Stocker les métadonnées des documents dans Neo4j.

3. **Extraction et stockage des variables**
   - Développer la logique d'extraction des variables via l'agent IA.
   - Stocker les variables extraites dans Neo4j, liées au document correspondant.

---

## Phase 4 : Implémentation de l'Agent IA et des Scénarios

1. **Configuration de l'agent IA**
   - Intégrer un LLM pour les tâches d'extraction et de génération.
   - Configurer l'agent pour utiliser des outils spécifiques (ex. : extraction de texte, parsing).

2. **Définition des scénarios**
   - Créer des scénarios types (ex. : fin de contrat, réception de facture).
   - Associer chaque scénario à des documents et variables spécifiques.

3. **Exécution automatisée**
   - Implémenter la logique d'exécution des scénarios via `BackgroundTasks`.
   - Assurer que l'agent IA récupère les documents, extrait les variables, et effectue les actions requises (ex. : remplir un formulaire).

---

## Phase 5 : Tests et Validation

1. **Tests unitaires**
   - Tester les endpoints API avec Pytest.
   - Vérifier les interactions avec Neo4j et MinIO.

2. **Tests d'intégration**
   - Simuler des cas d'usage complets (ex. : création et exécution d'un scénario).
   - Valider l'extraction correcte des variables et la mise à jour des données.

3. **Tests de l'agent IA**
   - Tester la précision de l'extraction sur différents types de documents.

---

## Phase 6 : Documentation et Finalisation

1. **Rédaction de la documentation**
   - README : Instructions pour démarrer le projet.
   - Document technique : Description de l'architecture, justification du modèle IA, et détails sur les entités et fonctionnalités.

2. **Préparation pour la soumission**
   - Vérifier le `Dockerfile` et `docker-compose.yml`.
   - Assurer que le code est propre, commenté, et suit les standards PEP8.

---

Ce roadmap intègre toutes les exigences de fonctionnalités et d'entités, vous guidant pas à pas vers un projet complet et conforme aux spécifications.