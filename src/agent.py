"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme client principal.
"""

import logging
import json
import uuid
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from langchain.agents import initialize_agent, Tool, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain.memory import ConversationBufferMemory
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.tools.tools import extract_variables, generate_from_template, submit_form, safe_parse_json
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
from src.config import Config as settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    drv = Neo4jDriver(
        uri=settings.get_neo4j_uri(),
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD
    )
    results = drv._run_tx(query, params or {})
    drv.close()
    return results  # déjà list[dict] dans _run_tx


def generate_email_tool(template: str, variables: Dict[str, Any]) -> str:
    return generate_from_template(template, variables)


def fill_template_tool(template: str, variables: Dict[str, Any]) -> str:
    return generate_from_template(template, variables)


def extract_variables_tool(content: bytes, filename: str) -> Dict[str, Any]:
    return extract_variables(content, filename)


def submit_form_tool(url: str, data: Dict[str, Any], timeout: int = settings.WEB_TIMEOUT) -> Dict[str, Any]:
    return submit_form(url, data, timeout)


def generate_pdf(html: str) -> bytes:
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

# Initialisation de la mémoire pour l'agent
agent_memory = ConversationBufferMemory(
    memory_key="chat_history", return_messages=True
)

# Initialisation de l'agent multi-outils
agent_executor = AgentExecutor.from_agent_and_tools(
    agent=initialize_agent(
        tools=TOOLS,
        llm=client,
        agent="zero-shot-react-description",
        verbose=True,
        memory=agent_memory
    ),
    tools=TOOLS,
    verbose=True,
    handle_parsing_errors=True,
    memory=agent_memory
)

# Load prompt from external markdown
action_plan_md = Path(__file__).parent.parent / 'data' / 'action_planning.md'
ACTION_PLANNING_TEMPLATE = action_plan_md.read_text()

# Build prompt template
action_planning_prompt = ChatPromptTemplate.from_template(ACTION_PLANNING_TEMPLATE) | client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(
        (ValueError, KeyError, json.JSONDecodeError)),
    reraise=True
)
def run_agent_tool(tool_name: str, *args, **kwargs):
    logger.info(f"[AGENT] Lancement du tool: {tool_name}")
    tool = next((t for t in TOOLS if t.name == tool_name), None)
    if not tool:
        logger.error(f"Outil {tool_name} non trouvé.")
        raise ValueError(f"Outil {tool_name} non trouvé.")
    try:
        result = tool.func(*args, **kwargs)
        logger.info(f"[AGENT] Tool {tool_name} exécuté avec succès")
        return result
    except Exception as e:
        logger.error(f"[AGENT] Erreur lors de l'exécution de {tool_name}: {e}")
        logger.debug(traceback.format_exc())
        raise


def preprocess_document(content: bytes, filename: str) -> Dict[str, Any]:
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    doc_type = "unknown"
    if ext in ['pdf', 'doc', 'docx']:
        if "facture" in filename.lower():
            doc_type = "invoice"
        elif "contrat" in filename.lower():
            doc_type = "contract"
        else:
            doc_type = "document"
    elif ext in ['csv', 'xls', 'xlsx']:
        doc_type = "spreadsheet"
    elif ext in ['eml', 'msg']:
        doc_type = "email"
    return {"content": content, "type": doc_type, "extension": ext, "size": len(content)}


def create_dynamic_scenario(
    document_content: bytes, filename: str, scenario_nature: str, driver: Optional[Neo4jDriver] = None
) -> dict:
    from src.config import config
    from scripts.minio_manager import MinioManager

    execution_log = []
    start_time = datetime.utcnow()

    try:
        # Driver init
        if driver is None:
            driver = Neo4jDriver()

        # 1. Création du scénario sans étapes manuelles
        scenario_name = f"Scénario {scenario_nature} {start_time.isoformat()}"
        scenario_desc = f"Automatisation IA pour {scenario_nature}"
        scenario_id = driver.create_scenario(
            nom=scenario_name,
            description=scenario_desc,
            priorite="moyenne",
            document_ids=[],
            variables=[],
            etapes=[]
        )
        execution_log.append(
            {"step": "create_scenario", "status": "success", "id": scenario_id})

        # 2. Upload dans MinIO
        minio_conf = config.get_minio_config()
        minio_manager = MinioManager(**minio_conf)
        minio_manager.upload_file(
            document_content, filename, "application/octet-stream")
        execution_log.append(
            {"step": "upload_document", "status": "success", "key": filename})

        # 3. Création du document et lien
        doc_id = driver.create_document(
            titre=filename, type="automatique", minio_key=filename, statut="actif"
        )
        driver.link_scenario_to_document(scenario_id, doc_id)
        execution_log.append(
            {"step": "create_document", "status": "success", "id": doc_id})

        # 4. Prétraitement
        pre = preprocess_document(document_content, filename)

        # 5. Préparer le prompt
        context = f"""
        Type: {scenario_nature}
        Description: {scenario_desc}
        Document: {filename} (type={pre['type']})
        Scenario ID: {scenario_id}
        """

        # 6. Appel agent pour plan d’actions
        agent_memory.clear()
        raw = agent_executor.invoke({
            "input": context,
            "filename": filename,
            "scenario_nature": scenario_nature
        })
        if isinstance(raw, dict) and "output" in raw:
            raw_plan = raw["output"]
        else:
            raw_plan = raw
        plan = safe_parse_json(raw_plan)
        actions = plan.get("actions", []) if isinstance(plan, dict) else []

        execution_log.append(
            {"step": "parse_plan", "status": "success", "count": len(actions)})

        # 7a. Stocker le plan dans Neo4j
        driver.update_scenario_etapes(scenario_id, actions)

        # 7b. (Optionnel) créer et lier chaque Step
        for idx, act in enumerate(actions):
            step_id = driver.create_node("Step", {
                "id": str(uuid.uuid4()),
                "outil": act["tool"],
                "params": json.dumps(act.get("parameters", {})),
                "ordre": idx+1
            })
            driver.link_nodes("Scenario", scenario_id,
                              "HAS_STEP", "Step", step_id)

        # 8. Exécuter chaque action
        results = []
        for i, act in enumerate(actions):
            tool = act.get("tool")
            params = act.get("parameters", {}) or {}
            try:
                res = run_agent_tool(tool, **params)
                # Si extraction, stocker variables
                if tool == "extract_variables" and isinstance(res, dict):
                    for k, v in res.items():
                        if v is not None:
                            driver.link_variable_to_document(
                                document_id=doc_id,
                                variable_nom=k,
                                variable_valeur=str(v),
                                variable_type=type(v).__name__
                            )
                results.append({"step": i+1, "tool": tool,
                               "status": "success", "result": res})
            except Exception as e:
                results.append({"step": i+1, "tool": tool,
                               "status": "error", "error": str(e)})

        # 9. Clôture du scénario
        driver.update_scenario(
            scenario_id,
            statut="completed",
            resultat=json.dumps({"actions": results})
        )
        return {
            "scenario_id": scenario_id,
            "document_id": doc_id,
            "status": "success",
            "actions": results,
            "explanation": plan.get("explanation", ""),
            "log": execution_log,
            "duration": (datetime.utcnow()-start_time).total_seconds()
        }

    except Exception as e:
        logger.error(f"Error in create_dynamic_scenario: {e}")
        logger.debug(traceback.format_exc())
        try:
            driver.update_scenario(
                scenario_id, statut="error", resultat=json.dumps({"error": str(e)}))
        except:
            pass
        return {"status": "error", "error": str(e), "log": execution_log}
