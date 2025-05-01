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

from langchain.agents import create_react_agent, Tool, AgentExecutor
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
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
llm = ChatGroq(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL)

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


def link_variable_to_document_tool(document_id: str, variable_id: str) -> list:
    """Link an existing variable node to a document node in Neo4j"""
    query = (
        "MATCH (d:Document {id: $did}), (v:Variable {id: $vid}) "
        "MERGE (d)-[:HAS_VARIABLE]->(v)"
    )
    return run_cypher(query, {"did": document_id, "vid": variable_id})


def link_scenario_to_variable_tool(scenario_id: str, variable_id: str) -> list:
    """Link an existing variable node to a scenario node in Neo4j"""
    query = (
        "MATCH (s:Scenario {id: $sid}), (v:Variable {id: $vid}) "
        "MERGE (s)-[:USES_VARIABLE]->(v)"
    )
    return run_cypher(query, {"sid": scenario_id, "vid": variable_id})


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
    Tool(name="link_variable_to_document", func=link_variable_to_document_tool,
         description="Lier une variable existante à un document Neo4j"),
    Tool(name="link_scenario_to_variable", func=link_scenario_to_variable_tool,
         description="Lier une variable existante à un scénario Neo4j"),
]

# Load prompt from external markdown
action_plan_md = Path(__file__).parent.parent / 'data' / 'action_planning.md'
ACTION_PLANNING_TEMPLATE = action_plan_md.read_text()

# Build prompt template
action_planning_prompt = PromptTemplate.from_template(
    ACTION_PLANNING_TEMPLATE) | llm

agent = create_react_agent(llm=llm, tools=TOOLS, prompt=action_planning_prompt)

# Initialisation de l'agent multi-outils
agent_executor = AgentExecutor.from_agent_and_tools(
    agent=agent,
    tools=TOOLS,
    verbose=True,
    handle_parsing_errors=True,
)