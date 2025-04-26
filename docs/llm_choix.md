# Choix des LLMs pour l’automatisation de scénarios métier

## 1. Critères de sélection

Le choix des modèles de langage (LLM) repose sur les critères suivants :
- **Performance** : Qualité de l’extraction/génération, compréhension métier
- **Coût** : Facturation à l’usage, open-source vs. propriétaire
- **Latence** : Rapidité de réponse, important pour l’automatisation
- **Confidentialité** : Données sensibles, hébergement cloud ou local
- **Interopérabilité** : Intégration avec LangChain, API Python
- **Paramètres techniques** : Nom du modèle, fournisseur, version, taille, endpoint, clé API

## 2. Modèles retenus et paramètres

### Extraction de variables
- **Modèle** : Llama-2-70B
- **Fournisseur** : Groq Cloud
- **Version** : 70B
- **Endpoint** : https://api.groq.com/openai/v1/chat/completions
- **Clé API** : fournie via la variable d’environnement `LLM_API_KEY`
- **Paramètres d’appel** :
  - `model`: "llama2-70b-4096"
  - `temperature`: 0.2 (pour extraction fiable)
  - `max_tokens`: 1024
- **Justification** :
  - Excellente compréhension du texte métier et des instructions complexes
  - Open-source, coût modéré, support natif Groq Cloud et LangChain
  - Latence très faible sur Groq Cloud

### Génération de contenu (email, template)
- **Modèle** : Mixtral-8x7B
- **Fournisseur** : Groq Cloud
- **Version** : 8x7B
- **Endpoint** : https://api.groq.com/openai/v1/chat/completions
- **Clé API** : fournie via la variable d’environnement `LLM_API_KEY`
- **Paramètres d’appel** :
  - `model`: "mixtral-8x7b-32768"
  - `temperature`: 0.7 (pour génération créative)
  - `max_tokens`: 2048
- **Justification** :
  - Très performant pour la génération de texte naturel, structuré et professionnel
  - Optimisé pour le coût et la rapidité sur Groq Cloud
  - Facilement intégrable avec LangChain et PromptTemplate

### Remplissage de template HTML
- **Outil** : Jinja2 (local)
- **Justification** :
  - Pas besoin d’un LLM pour ce type de tâche : rapidité, coût nul, robustesse

### Soumission de formulaire web
- **Outil** : Playwright (non LLM)
- **Justification** :
  - Automatisation fiable et reproductible, pas de génération de texte

## 3. Intégration technique
- Les prompts sont gérés via PromptTemplate (LangChain) pour garantir la clarté, la réutilisabilité et la compatibilité avec différents LLMs.
- Les clés API et modèles sont configurables dans le fichier de configuration (`src/config.py`).
- Les choix sont documentés dans le code (`src/tools/tools.py`) et dans la documentation technique.

## 4. Évolutivité
- Le système est conçu pour permettre le changement de LLM facilement (autre modèle Groq, OpenAI, local, etc.) selon les besoins futurs (coût, confidentialité, performance).

---

**Résumé des paramètres LLM utilisés :**

| Usage                | Modèle         | Fournisseur | Version | Paramètres principaux                |
|----------------------|---------------|-------------|---------|--------------------------------------|
| Extraction variables | Llama-2-70B   | Groq Cloud  | 70B     | model=llama2-70b-4096, temp=0.2      |
| Génération email     | Mixtral-8x7B  | Groq Cloud  | 8x7B    | model=mixtral-8x7b-32768, temp=0.7   |
| Template HTML        | Jinja2        | Local       | -       | -                                    |
| Formulaire web       | Playwright    | Local       | -       | -                                    |

