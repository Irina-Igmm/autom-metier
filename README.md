# Automatisation de scénarios métier pilotée par un agent IA

## Objectif
Automatiser des scénarios métier complexes (extraction de variables, génération de documents, interactions web) orchestrés par un agent IA, avec stockage des graphes dans Neo4j et des documents dans MinIO.

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
- **Agent IA** : Orchestration des outils métier (extraction, génération, soumission web)
- **Groq Cloud (LLM)** : Extraction de variables et génération de contenu via Llama-2 et Mixtral, prompts gérés avec PromptTemplate (LangChain)
- **Playwright** : Automatisation réelle de la soumission de formulaires web

### Pipeline d'un scénario
1. Création d'un scénario via POST `/scenarios/` (stockage dans Neo4j, liens vers documents/variables)
2. Déclenchement d'un scénario via POST `/scenarios/{id}/run` (BackgroundTasks)
   - Téléchargement du document depuis MinIO
   - Extraction/inscription de variables par l'agent IA (LLM Groq Cloud)
   - Génération d'email ou remplissage de template (LLM ou Jinja2)
   - Soumission automatisée de formulaire web (Playwright)
   - Génération et upload du résultat sur MinIO
   - Mise à jour du graphe Neo4j

## Lancement local
1. Cloner le dépôt
2. Copier `.env.example` en `.env` et adapter les variables
3. Démarrer l'infra :
   ```bash
   docker-compose -f infra/docker-compose.yml up --build
   ```
4. Lancer l'API :
   ```bash
   uvicorn main:app --reload
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
