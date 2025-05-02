# Automatisation de scénarios métier pilotée par un agent IA

## Objectif
Automatiser des scénarios métier complexes (extraction de variables, génération de documents, interactions web) orchestrés dynamiquement par un agent IA, avec stockage des graphes dans Neo4j et des documents dans MinIO.

## Structure du projet

```
├── src/        # Code source principal (FastAPI, agents, outils, modèles)
├── tests/      # Tests unitaires et d'intégration
├── infra/      # Infrastructure (Dockerfile, docker-compose, config)
├── docs/       # Documentation, notebooks, schémas
├── main.py     # Point d'entrée FastAPI (exécuté par Uvicorn)
```

## Architecture
- **FastAPI** : API REST, endpoints sécurisés, gestion des tâches asynchrones (BackgroundTasks)
- **Neo4j** : Base de données graphe pour modéliser les entités (Document, Variable, Scenario, Automatisation)
- **MinIO** : Stockage objet pour documents et résultats
- **Agent IA** : Orchestration dynamique des outils métier (extraction, génération, soumission web) via LLM
- **Groq Cloud (LLM)** : Extraction de variables, génération de contenu, et planification dynamique via Llama-2/Mixtral (LangChain)
- **Playwright** : Automatisation réelle de la soumission de formulaires web

## Fonctionnement centré sur l’agent IA

L’automatisation repose sur un agent IA multi-outils : chaque tâche d’un scénario (extraction, génération, remplissage, soumission) est orchestrée dynamiquement par l’agent, sans logique codée en dur. Le plan d’action est généré à la volée par le LLM selon le contexte du scénario et les variables extraites.

### Pipeline automatisé

1. **Création de scénario** (`POST /scenarios/`) : le scénario est enregistré dans Neo4j, les documents sont stockés dans MinIO.
2. **Exécution automatisée** (`POST /scenarios/{id}/run`) :
   - L’agent IA récupère le scénario et les documents
   - Extrait les variables pertinentes
   - Génère dynamiquement le plan d’action (outils, ordre, paramètres)
   - Exécute chaque tâche via les outils Python accessibles
   - Met à jour Neo4j et MinIO à chaque étape

### Outils accessibles par l’agent

- Extraction de variables (LLM)
- Génération d’email (LLM)
- Remplissage de template HTML (Jinja2)
- Soumission de formulaire web (Playwright)
- Manipulation de graphes Neo4j

### Avantages

- **Aucune logique manuelle** : tout est orchestré par l’agent IA
- **Extensible** : ajout de nouveaux scénarios sans modifier le code
- **Traçabilité** : chaque étape est enregistrée dans Neo4j

## Lancement local
1. Cloner le dépôt :
   ```bash
   git clone <repo-url>
   cd automatisation-metier
   ```
2. Copier et adapter la configuration :
   ```bash
   cp .env.example .env
   ```
   Renseigner les variables (Neo4j URI/credentials, MinIO credentials, LLM_API_KEY, etc.).
3. (Optionnel) Initialiser Neo4j (si nécessaire) :
   ```bash
   docker-compose -f infra/docker-compose.yml run --rm fastapi python scripts/init_neo4j.py
   ```
4. Démarrer tous les services en arrière-plan :
   ```bash
   docker-compose -f infra/docker-compose.yml up -d --build
   ```
5. Vérifier les services :
   ```bash
   docker-compose -f infra/docker-compose.yml ps
   ```
6. Accéder :
   - API FastAPI : http://localhost:8000 (docs à http://localhost:8000/docs)
   - Neo4j : http://localhost:7474 (login: neo4j / test2025*7)
   - MinIO Console : http://localhost:9001 (login: adminminio2025 / SuperSecretKey2025)
7. Suivre les logs (facultatif) :
   ```bash
   docker-compose -f infra/docker-compose.yml logs -f
   ```

## Lancement sur Google Colab
- Un notebook dans `docs/` permet de tester l'API, l'agent et les outils étape par étape (sans GPU requis).

## Tests
- Lancer les tests unitaires et d'intégration :
  ```bash
  pytest tests/
  ```
- Utilisation de testcontainers pour Neo4j et simulation MinIO.

## Choix du modèle IA et outils
- **Groq Cloud** : Llama-2-70B pour l'extraction de variables, Mixtral-8x7B pour la génération d'email (choix justifié pour performance, coût, latence, open-source).
- **LangChain** : Orchestration des prompts et outils via PromptTemplate.
- **Jinja2** : Remplissage de templates HTML localement.
- **Playwright** : Soumission automatisée de formulaires web (remplace la simulation).

## Exemples de scénarios
- Fin de contrat fournisseur : extraction de date, génération d'email, stockage du résultat
- Réception de facture : extraction de variables, vérification de doublons, génération d'accusé
- Relance impayé : détection, génération de mail structuré
- Ajout de produit : extraction, création de relations dans Neo4j

## Bonnes pratiques
- Code PEP8, commenté, structuré
- Robustesse : gestion des erreurs, timeouts, retries
- Documentation claire et complète

## Production
- Déploiement via Docker Compose
- Variables d'environnement documentées
- Prêt pour hébergement sur GitHub
