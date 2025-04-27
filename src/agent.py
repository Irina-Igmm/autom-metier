"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme client principal.
"""

import logging
from langchain.agents import initialize_agent, Tool, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain.chains import LLMChain
from src.tools.tools import (
    extract_variables_from_document,
    generate_email,
    fill_html_template,
    submit_web_form,
)
from src.config import Config as settings

# Initialisation du client Groq Cloud
client = ChatGroq(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL)

# Définition des outils accessibles par l'agent
TOOLS = [
    Tool(
        name="extract_variables",
        func=extract_variables_from_document,
        description="Extraction de variables clés à partir d'un document brut.",
    ),
    Tool(
        name="generate_email",
        func=generate_email,
        description="Génération d'un email à partir de variables et d'un template.",
    ),
    Tool(
        name="fill_html_template",
        func=fill_html_template,
        description="Remplissage d'un template HTML ou texte avec des variables.",
    ),
    Tool(
        name="submit_web_form",
        func=submit_web_form,
        description="Soumission automatisée d'un formulaire web.",
    ),
]

# Définition des descriptions des types de scénarios (pour l'agent)
SCENARIO_DESCRIPTIONS = {
    "contract_end": "Détection de fin de contrat et génération automatique d'email de renouvellement",
    "invoice_receipt": "Traitement de facture entrante, vérification des doublons et génération d'accusé de réception",
    "unpaid_invoice": "Détection de facture impayée et génération d'email de relance",
    "product_catalog": "Extraction de produits depuis un catalogue et création des relations dans Neo4j",
}

# Initialisation de l'agent multi-outils avec ReAct
agent_executor = AgentExecutor.from_agent_and_tools(
    agent=initialize_agent(
        tools=TOOLS, llm=client, agent="zero-shot-react-description", verbose=True
    ),
    tools=TOOLS,
    verbose=True,
    handle_parsing_errors=True,
)

# Template de prompt pour déterminer le plan d'action
ACTION_PLANNING_TEMPLATE = """
Tu es un assistant d'automatisation de scénarios métier. 
Tu as reçu un document de type {scenario_type} : {scenario_description}.
Tu as extrait les variables suivantes du document : {variables}

Voici les outils dont tu disposes :
1. extract_variables - Pour extraire des données d'un document
2. generate_email - Pour générer un email basé sur un template et des variables
3. fill_html_template - Pour remplir un template HTML avec des variables
4. submit_web_form - Pour soumettre automatiquement un formulaire web

En te basant sur le type de scénario et les variables extraites, détermine :
1. Quelles actions exécuter
2. Dans quel ordre
3. Avec quels paramètres

Réponds sous forme de liste d'actions en JSON. Par exemple :
```json
{
  "actions": [
    {
      "tool": "nom_outil",
      "parameters": {
        "param1": "valeur1",
        "param2": "valeur2"
      }
    }
  ],
  "explanation": "Explication du plan d'action"
} """

action_planning_prompt = ChatPromptTemplate.from_template(ACTION_PLANNING_TEMPLATE)
# action_planner = LLMChain(llm=client, prompt=action_planning_prompt)
action_planner = action_planning_prompt | client


def run_agent_tool(tool_name: str, *args, **kwargs):
    logging.info(f"[AGENT] Lancement du tool: {tool_name}")
    for tool in TOOLS:
        if tool.name == tool_name:
            return tool.func(*args, **kwargs)
    raise ValueError(f"Outil {tool_name} non trouvé.")


def create_dynamic_scenario(
    document_content: bytes, filename: str, scenario_nature: str, driver=None
) -> dict:
    """
    Crée et exécute dynamiquement un scénario métier centré sur l'agent IA et la base Neo4j.
    L'agent multi-outils reçoit le contexte et la consigne, puis choisit et enchaîne les outils de façon autonome.
    """
    import json
    from src.neo4j_driver import neo4j_driver
    from scripts.minio_manager import MinioManager
    from src.config import config
    from datetime import datetime

    if driver is None:
        driver = neo4j_driver
    scenario_name = f"Scénario {scenario_nature} {datetime.utcnow().isoformat()}"
    scenario_desc = f"Automatisation IA pour {scenario_nature} (créé automatiquement)"
    scenario_id = driver.create_scenario(
        nom=scenario_name,
        description=scenario_desc,
        priorite="moyenne",
        document_ids=[],
        variables=[],
    )
    minio_conf = config.get_minio_config()
    minio_manager = MinioManager(
        minio_conf["endpoint"],
        minio_conf["access_key"],
        minio_conf["secret_key"],
        minio_conf["bucket"],
        secure=minio_conf["secure"],
    )
    minio_manager.upload_file(document_content, filename, "application/octet-stream")
    doc_id = driver.create_document(
        nom=filename,
        type_doc="automatique",
        chemin=filename,
        statut="actif",
    )
    driver.link_scenario_to_document(scenario_id, doc_id)
    # Construit le contexte pour l'agent
    context = f"""
    Tu es un agent d'automatisation métier. Voici le contexte :
    - Type de scénario : {scenario_nature}
    - Description : {scenario_desc}
    - Document : {filename}
    - ID Neo4j : {scenario_id}
    - Le document est disponible en bytes (binaire).
    Ta mission :
    1. Extraire les variables pertinentes du document.
    2. Générer dynamiquement le plan d'action (outils, ordre, paramètres).
    3. Exécuter chaque tâche utile (extraction, génération, remplissage, soumission, etc.)
    4. Mettre à jour Neo4j et MinIO si besoin.
    Retourne un rapport structuré des actions réalisées.
    """
    # L'agent multi-outils agit de façon autonome
    try:
        result = agent_executor.invoke(
            {
                "input": context,
                "document_content": document_content,
                "filename": filename,
                "scenario_nature": scenario_nature,
                "neo4j_scenario_id": scenario_id,
            }
        )
    except Exception as e:
        result = {"error": str(e)}
    return {
        "scenario_id": scenario_id,
        "document_id": doc_id,
        "agent_result": result,
    }
