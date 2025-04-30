"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme client principal.
"""

import logging
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import traceback

from langchain.agents import initialize_agent, Tool, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq
from langchain.memory import ConversationBufferMemory
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.tools.tools import extract_variables, generate_from_template, submit_form, safe_parse_json
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
import io
from src.config import Config as settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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

# Initialisation d'une mémoire pour l'agent
agent_memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

# Initialisation de l'agent multi-outils avec mémoire
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


@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ValueError, KeyError, json.JSONDecodeError)),
    reraise=True
)
def run_agent_tool(tool_name: str, *args, **kwargs):
    """
    Execute a tool with retry logic and enhanced error handling.
    
    Args:
        tool_name: Name of the tool to execute
        *args: Positional arguments for the tool
        **kwargs: Keyword arguments for the tool
        
    Returns:
        The result of the tool execution
        
    Raises:
        ValueError: If the tool is not found
        Exception: If the tool execution fails after retries
    """
    logger.info(f"[AGENT] Lancement du tool: {tool_name}")
    
    # Find the tool in available tools
    tool = next((t for t in TOOLS if t.name == tool_name), None)
    if not tool:
        logger.error(f"Outil {tool_name} non trouvé.")
        raise ValueError(f"Outil {tool_name} non trouvé.")
        
    try:
        # Execute the tool and log success
        result = tool.func(*args, **kwargs)
        logger.info(f"[AGENT] Tool {tool_name} exécuté avec succès")
        return result
    except Exception as e:
        # Log detailed error and stack trace
        logger.error(f"[AGENT] Erreur lors de l'exécution de {tool_name}: {str(e)}")
        logger.debug(f"Stack trace: {traceback.format_exc()}")
        raise


def preprocess_document(content: bytes, filename: str) -> Dict[str, Any]:
    """
    Preprocess document content based on document type.
    Add specialized handling for different document formats.
    
    Args:
        content: Raw document content in bytes
        filename: Name of the document file
        
    Returns:
        Dictionary with preprocessed content and metadata
    """
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    doc_type = "unknown"
    
    # Identify document type
    if ext in ['pdf', 'doc', 'docx']:
        if "facture" in filename.lower() or "invoice" in filename.lower():
            doc_type = "invoice"
        elif "contrat" in filename.lower() or "contract" in filename.lower():
            doc_type = "contract"
        else:
            doc_type = "document"
    elif ext in ['csv', 'xls', 'xlsx']:
        doc_type = "spreadsheet"
    elif ext in ['eml', 'msg']:
        doc_type = "email"
    
    return {
        "content": content,
        "type": doc_type,
        "extension": ext,
        "size": len(content)
    }


def create_dynamic_scenario(
    document_content: bytes, filename: str, scenario_nature: str, driver=None
) -> dict:
    """
    Crée et exécute dynamiquement un scénario métier centré sur l'agent IA et la base Neo4j.
    L'agent multi-outils reçoit le contexte et la consigne, puis choisit et enchaîne les outils de façon autonome.
    
    Args:
        document_content: Content of the document in bytes
        filename: Name of the document file
        scenario_nature: Nature/type of the scenario
        driver: Optional Neo4j driver instance
        
    Returns:
        Dictionary with scenario execution results
    """
    from src.neo4j_driver import Neo4jDriver
    from scripts.minio_manager import MinioManager
    from src.config import config
    from datetime import datetime

    # Initialize tracking
    execution_log = []
    start_time = datetime.utcnow()
    
    try:
        # Initialize driver if not provided
        if driver is None:
            driver = Neo4jDriver()
            
        # Step 1: Create scenario in Neo4j
        logger.info(f"Creating scenario: {scenario_nature}")
        scenario_name = f"Scénario {scenario_nature} {start_time.isoformat()}"
        scenario_desc = f"Automatisation IA pour {scenario_nature} (créé automatiquement)"
        
        scenario_id = driver.create_scenario(
            nom=scenario_name,
            description=scenario_desc,
            priorite="moyenne",
            document_ids=[],
            variables=[],
        )
        execution_log.append({"step": "create_scenario", "status": "success", "id": scenario_id})
        
        # Step 2: Store document in MinIO
        logger.info(f"Uploading document to MinIO: {filename}")
        minio_conf = config.get_minio_config()
        minio_manager = MinioManager(
            minio_conf["endpoint"],
            minio_conf["access_key"],
            minio_conf["secret_key"],
            minio_conf["bucket"],
            secure=minio_conf["secure"],
        )
        
        upload_result = minio_manager.upload_file(
            document_content, filename, "application/octet-stream")
        execution_log.append({"step": "upload_document", "status": "success", "key": filename})
        
        # Step 3: Create document in Neo4j and link to scenario
        logger.info(f"Creating document in Neo4j: {filename}")
        doc_id = driver.create_document(
            titre=filename,
            type="automatique",
            minio_key=filename,
            statut="actif"
        )
        driver.link_scenario_to_document(scenario_id, doc_id)
        execution_log.append({"step": "create_document", "status": "success", "id": doc_id})
        
        # Step 4: Preprocess document based on type
        preprocessed = preprocess_document(document_content, filename)
        
        # Step 5: Build context for the agent with document type information
        context = f"""
        Tu es un agent d'automatisation métier. Voici le contexte :
        - Type de scénario : {scenario_nature}
        - Description : {scenario_desc}
        - Document : {filename}
        - Type de document : {preprocessed['type']}
        - ID Neo4j : {scenario_id}
        - Le document est disponible en bytes (binaire).
        
        Ta mission :
        1. Extraire les variables pertinentes du document.
        2. Générer dynamiquement le plan d'action (outils, ordre, paramètres).
        3. Exécuter chaque tâche utile (extraction, génération, remplissage, soumission, etc.)
        4. Mettre à jour Neo4j et MinIO si besoin.
        
        Retourne un rapport structuré des actions réalisées au format JSON avec la structure suivante:
        {{
          "actions": [
            {{
              "tool": "nom_outil",
              "parameters": {{ "param1": "valeur1" }}
            }}
          ],
          "explanation": "Explication du plan d'action"
        }}
        """
        
        # Step 6: Invoke agent and parse response with robust error handling
        logger.info("Invoking AI agent")
        try:
            # Reset memory for new scenario
            agent_memory.clear()
            
            # Invoke agent with context and document details
            raw_response = agent_executor.invoke(
                {
                    "input": context,
                    "document_content": document_content,
                    "filename": filename,
                    "scenario_nature": scenario_nature,
                    "neo4j_scenario_id": scenario_id,
                    "document_type": preprocessed["type"]
                }
            )
            execution_log.append({"step": "agent_invocation", "status": "success"})
            
            # Parse the agent's plan with enhanced error handling
            try:
                # If it's already a dict, use it directly
                if isinstance(raw_response, dict) and "output" in raw_response:
                    raw_plan = raw_response["output"]
                else:
                    raw_plan = raw_response
                
                # Try to extract JSON from the response
                plan = {}
                if isinstance(raw_plan, str):
                    # Use safe_parse_json from tools.py for robust JSON extraction
                    plan = safe_parse_json(raw_plan)
                elif isinstance(raw_plan, dict):
                    plan = raw_plan
                
                # Extract actions with fallbacks
                actions = []
                if "actions" in plan and isinstance(plan["actions"], list):
                    actions = plan["actions"]
                elif "steps" in plan and isinstance(plan["steps"], list):
                    actions = plan["steps"]
                elif isinstance(plan, list):
                    actions = plan
                
                execution_log.append({"step": "parse_plan", "status": "success", "action_count": len(actions)})
                
            except Exception as e:
                logger.error(f"Error parsing agent response: {str(e)}")
                execution_log.append({"step": "parse_plan", "status": "error", "error": str(e)})
                actions = []
                
            # Step 7: Execute each action with enhanced error handling and retry logic
            results = []
            for i, act in enumerate(actions):
                if isinstance(act, dict):
                    tool_name = act.get("tool") or act.get("name")
                    params = act.get("parameters") or act.get("params") or {}
                    
                    if tool_name:
                        logger.info(f"Executing action {i+1}/{len(actions)}: {tool_name}")
                        try:
                            # Execute tool with retry logic
                            result = run_agent_tool(tool_name, **params)
                            
                            # Store variable extraction results in Neo4j if applicable
                            if tool_name == "extract_variables" and isinstance(result, dict):
                                for var_key, var_value in result.items():
                                    if var_key != "error" and var_value:
                                        var_id = driver.create_variable(
                                            key=var_key,
                                            value=str(var_value),
                                            document_id=doc_id
                                        )
                                        logger.info(f"Created variable: {var_key}={var_value}")
                            
                            results.append({
                                "step": i+1,
                                "tool": tool_name,
                                "status": "success",
                                "result": result
                            })
                        except Exception as ex:
                            logger.error(f"Error executing tool {tool_name}: {str(ex)}")
                            results.append({
                                "step": i+1,
                                "tool": tool_name,
                                "status": "error",
                                "error": str(ex)
                            })
            
            # Update scenario status in Neo4j
            driver.update_scenario(
                scenario_id, 
                statut="completed",
                resultat=json.dumps({"actions": results})
            )
            
            return {
                "scenario_id": scenario_id,
                "document_id": doc_id,
                "status": "success",
                "actions_executed": results,
                "plan_explanation": plan.get("explanation", ""),
                "execution_log": execution_log,
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Agent execution error: {str(e)}")
            logger.debug(traceback.format_exc())
            
            # Update scenario status in Neo4j
            try:
                driver.update_scenario(scenario_id, statut="error", resultat=json.dumps({"error": str(e)}))
            except Exception:
                pass
                
            return {
                "scenario_id": scenario_id,
                "document_id": doc_id,
                "status": "error",
                "error": str(e),
                "execution_log": execution_log,
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
            }
            
    except Exception as e:
        logger.error(f"Scenario creation error: {str(e)}")
        logger.debug(traceback.format_exc())
        
        return {
            "status": "error",
            "error": str(e),
            "execution_log": execution_log,
            "execution_time": (datetime.utcnow() - start_time).total_seconds()
        }
