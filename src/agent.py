"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme client principal.
"""

import logging
from langchain.agents import initialize_agent, Tool, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from src.tools.tools import extract_variables, generate_from_template, submit_form
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
import io
from typing import Any, Dict, List
from src.config import Config as settings

# Initialisation du client LLM
client = ChatGroq(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL)

# Outils métier exposés


def s3_upload(content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    cfg = settings.get_minio_config()
    mgr = MinioManager(**cfg)
    return mgr.upload_file(content, filename, content_type)


def s3_download(filename: str) -> bytes:
    cfg = settings.get_minio_config()
    mgr = MinioManager(**cfg)
    data = mgr.download_file(filename)
    return data.read()


def run_cypher(query: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    drv = Neo4jDriver(uri=settings.get_neo4j_uri(
    ), user=settings.NEO4J_USER, password=settings.NEO4J_PASSWORD)
    results = drv._run_tx(query, params or {})
    drv.close()
    return [record.data() for record in results]


def generate_email_tool(template: str, variables: Dict[str, Any]) -> str:
    return generate_from_template(template, variables)


def fill_template_tool(template: str, variables: Dict[str, Any]) -> str:
    return generate_from_template(template, variables)


def extract_variables_tool(content: bytes, filename: str) -> Dict[str, Any]:
    return extract_variables(content, filename)


def submit_form_tool(url: str, data: Dict[str, Any], timeout: int = settings.WEB_TIMEOUT) -> Dict[str, Any]:
    return submit_form(url, data, timeout)


def generate_pdf(html: str) -> bytes:
    # simple HTML-to-PDF via Jinja2 PDFKit or similar
    try:
        import pdfkit
        return pdfkit.from_string(html, False)
    except Exception:
        return b""


TOOLS = [
    Tool(name="s3_upload", func=s3_upload,
         description="Upload un objet dans MinIO"),
    Tool(name="s3_download", func=s3_download,
         description="Télécharger un objet depuis MinIO"),
    Tool(name="run_cypher", func=run_cypher,
         description="Exécuter une requête Cypher sur Neo4j"),
    Tool(name="extract_variables", func=extract_variables_tool,
         description="Extraire des variables d'un document"),
    Tool(name="generate_email", func=generate_email_tool,
         description="Générer un email via template"),
    Tool(name="fill_template", func=fill_template_tool,
         description="Remplir un template HTML"),
    Tool(name="submit_web_form", func=submit_form_tool,
         description="Soumission de formulaire web"),
    Tool(name="generate_pdf", func=generate_pdf,
         description="Générer un PDF à partir de HTML"),
]

# Initialisation de l'agent multi-outils
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

action_planning_prompt = ChatPromptTemplate.from_template(
    ACTION_PLANNING_TEMPLATE)
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
    from src.neo4j_driver import Neo4jDriver
    from scripts.minio_manager import MinioManager
    from src.config import config
    from datetime import datetime

    if driver is None:
        driver = Neo4jDriver()
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
    minio_manager.upload_file(
        document_content, filename, "application/octet-stream")
    # create_document matches Pydantic model fields
    doc_id = driver.create_document(
        titre=filename,
        type="automatique",
        minio_key=filename,
        statut="actif"
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
        raw_plan = agent_executor.invoke(
            {
                "input": context,
                "document_content": document_content,
                "filename": filename,
                "scenario_nature": scenario_nature,
                "neo4j_scenario_id": scenario_id,
            }
        )
        # parse JSON plan
        import json
        plan = raw_plan if isinstance(raw_plan, dict) else json.loads(raw_plan)
        actions = plan.get("actions", [])
    except Exception as e:
        return {"scenario_id": scenario_id, "document_id": doc_id, "error": str(e)}

    # exécuter chaque action via run_agent_tool
    results: List[Dict[str, Any]] = []
    for act in actions:
        name = act.get("tool")
        params = act.get("parameters", {})
        try:
            out = run_agent_tool(name, **params)
        except Exception as ex:
            out = {"error": str(ex)}
        results.append({"tool": name, "result": out})

    return {
        "scenario_id": scenario_id,
        "document_id": doc_id,
        "actions_executed": results,
        "plan_explanation": plan.get("explanation")
    }
