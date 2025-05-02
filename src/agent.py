"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme client principal.
"""

import logging
import json
import traceback
from datetime import datetime
from typing import Any, Dict, List
from pathlib import Path
import base64

from langchain.agents import create_react_agent, AgentExecutor
from langchain.tools import StructuredTool
from langchain_groq import ChatGroq
from pydantic import BaseModel

# Import tools from the tools module
from src.tools.tools import (
    s3_upload,
    s3_download,
    run_cypher,
    extract_variables,
    generate_from_template,
    submit_form,
    generate_pdf,
    save_generated_result,
    create_variable,
    link_variable_to_document as link_variable_to_document_fn,
    link_scenario_to_variable as link_scenario_to_variable_fn
)
from src.neo4j_driver import Neo4jDriver
from src.config import Config as settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Modèles Pydantic pour les entrées des outils


class ExtractVariablesInput(BaseModel):
    content: str


class S3UploadInput(BaseModel):
    content: str  # base64 encodé
    filename: str
    content_type: str


class SaveGeneratedResultInput(BaseModel):
    content: str  # base64 encodé
    filename: str
    titre: str
    automatisation_id: str
    scenario_id: str
    content_type: str = "application/octet-stream"
    type_resultat: str = "document"
    variables_utilisees: list[str] = None
    metadonnees: dict[str, Any] = None


class RunCypherInput(BaseModel):
    query: str
    params: dict[str, Any] = None


class GenerateEmailInput(BaseModel):
    template: str
    variables: dict[str, Any]


class FillTemplateInput(BaseModel):
    template: str
    variables: dict[str, Any]


class SubmitWebFormInput(BaseModel):
    url: str
    data: dict[str, Any]
    timeout: int = settings.WEB_TIMEOUT


class GeneratePdfInput(BaseModel):
    html: str


class LinkVariableToDocumentInput(BaseModel):
    document_id: str
    variable_id: str


class LinkScenarioToVariableInput(BaseModel):
    scenario_id: str
    variable_id: str


class CreateVariableInput(BaseModel):
    nom: str
    valeur: str

# Fonctions wrapper pour les outils avec des paramètres bytes


# def tool_extract_variables(content_b64: str, filename: str) -> dict[str, Any]:
#     content_bytes = base64.b64decode(content_b64)
#     return extract_variables(content_bytes, filename)


def tool_s3_upload(content_b64: str, filename: str, content_type: str) -> dict[str, Any]:
    content_bytes = base64.b64decode(content_b64)
    return s3_upload(content_bytes, filename, content_type)


def tool_save_generated_result(content_b64: str, filename: str, titre: str, automatisation_id: str, scenario_id: str, content_type: str = "application/octet-stream", type_resultat: str = "document", variables_utilisees: list[str] = None, metadonnees: dict[str, any] = None) -> dict[str, str]:
    content_bytes = base64.b64decode(content_b64)
    return save_generated_result(content_bytes, filename, titre, automatisation_id, scenario_id, content_type, type_resultat, variables_utilisees, metadonnees)


class AutomationAgent:
    """
    Class to handle the automation agent and its tools
    """

    def __init__(self, api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL):
        """
        Initialize the agent with the necessary components
        """
        self.llm = ChatGroq(api_key=api_key, model=model, temperature=0.2)
        self.tools = self._create_tools()

        # Load prompt from external markdown
        action_plan_md = Path(__file__).parent / 'data' / 'action_planning.md'

        action_planning_template = action_plan_md.read_text()

        # Créer un prompt de chat plus approprié
        from langchain_core.prompts import ChatPromptTemplate

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", action_planning_template),
            ("human", "{input}"),
            ("ai", "{agent_scratchpad}"),
        ])
        # Create the agent with the updated prompt
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt,
        )

        # Initialize the agent executor with better error handling
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=10
        )

    def _create_tools(self) -> list[StructuredTool]:
        """
        Create and return the list of tools available to the agent
        """
        return [
            StructuredTool.from_function(
                func=extract_variables,
                name="extract_variables",
                description="Extraire des variables d'un document. Paramètres: content (str)",
                args_schema=ExtractVariablesInput,
            ),
            StructuredTool.from_function(
                func=tool_s3_upload,
                name="s3_upload",
                description="Upload un objet dans MinIO. Paramètres: content (str, base64 encoded), filename (str), content_type (str)",
                args_schema=S3UploadInput,
            ),
            StructuredTool.from_function(
                func=run_cypher,
                name="run_cypher",
                description="Exécuter une requête Cypher sur Neo4j. Paramètres: query (str), params (dict, optional)",
                args_schema=RunCypherInput,
            ),
            StructuredTool.from_function(
                func=self.generate_email_tool,
                name="generate_email",
                description="Générer un email via template. Paramètres: template (str), variables (dict)",
                args_schema=GenerateEmailInput,
            ),
            StructuredTool.from_function(
                func=self.fill_template_tool,
                name="fill_template",
                description="Remplir un template HTML. Paramètres: template (str), variables (dict)",
                args_schema=FillTemplateInput,
            ),
            StructuredTool.from_function(
                func=submit_form,
                name="submit_web_form",
                description="Soumission de formulaire web. Paramètres: url (str), data (dict), timeout (int, optional)",
                args_schema=SubmitWebFormInput,
            ),
            StructuredTool.from_function(
                func=generate_pdf,
                name="generate_pdf",
                description="Générer un PDF à partir de HTML. Paramètres: html (str)",
                args_schema=GeneratePdfInput,
            ),
            StructuredTool.from_function(
                func=tool_save_generated_result,
                name="save_generated_result",
                description="Sauvegarder un résultat généré dans MinIO et Neo4j. Paramètres: content (str, base64 encoded), filename (str), titre (str), automatisation_id (str), scenario_id (str), content_type (str, optional), type_resultat (str, optional), variables_utilisees (list of str, optional), metadonnees (dict, optional)",
                args_schema=SaveGeneratedResultInput,
            ),
            StructuredTool.from_function(
                func=self.link_variable_to_document_tool,
                name="link_variable_to_document",
                description="Lier une variable existante à un document Neo4j. Paramètres: document_id (str), variable_id (str)",
                args_schema=LinkVariableToDocumentInput,
            ),
            StructuredTool.from_function(
                func=self.link_scenario_to_variable_tool,
                name="link_scenario_to_variable",
                description="Lier une variable existante à un scénario Neo4j. Paramètres: scenario_id (str), variable_id (str)",
                args_schema=LinkScenarioToVariableInput,
            ),
            StructuredTool.from_function(
                func=create_variable,
                name="create_variable",
                description="Crée une variable dans Neo4j. Paramètres: nom (str), valeur (str). Retourne l'ID de la variable créée.",
                args_schema=CreateVariableInput,
            ),
        ]

    # Simple wrapper methods to maintain API compatibility
    def generate_email_tool(self, template: str, variables: Dict[str, Any]) -> str:
        """Generate an email from a template and variables"""
        return generate_from_template(template, variables)

    def fill_template_tool(self, template: str, variables: Dict[str, Any]) -> str:
        """Fill a template with variables"""
        return generate_from_template(template, variables)

    def save_generated_result_tool(self,
                                   content: bytes,
                                   filename: str,
                                   titre: str,
                                   automatisation_id: str,
                                   scenario_id: str,
                                   content_type: str = "application/octet-stream",
                                   type_resultat: str = "document",
                                   variables_utilisees: List[str] = None,
                                   metadonnees: Dict[str, Any] = None) -> Dict[str, str]:
        """Wrapper pour l'outil de sauvegarde des résultats"""
        return save_generated_result(
            content=content,
            filename=filename,
            titre=titre,
            automatisation_id=automatisation_id,
            scenario_id=scenario_id,
            content_type=content_type,
            type_resultat=type_resultat,
            variables_utilisees=variables_utilisees,
            metadonnees=metadonnees
        )

    def link_variable_to_document_tool(self, document_id: str, variable_id: str) -> list:
        """Link an existing variable node to a document node in Neo4j"""
        return link_variable_to_document_fn(document_id, variable_id)

    def link_scenario_to_variable_tool(self, scenario_id: str, variable_id: str) -> list:
        """Link an existing variable node to a scenario node in Neo4j"""
        return link_scenario_to_variable_fn(scenario_id, variable_id)

    def run(self, scenario_id: str, automation_id: str, document_ids: List[str] = None) -> Dict[str, Any]:
        """
        Run the agent with a specific scenario

        Args:
            scenario_id: ID of the scenario to execute
            automation_id: ID of the automation record in Neo4j
            document_ids: Optional list of document IDs to include in the execution

        Returns:
            Dict with execution results
        """
        logger.info(
            f"Running agent for scenario {scenario_id}, automation {automation_id}")

        try:
            # Get scenario details from Neo4j
            drv = Neo4jDriver()
            scenario_details = drv.get_scenario_with_relations(scenario_id)

            if not scenario_details:
                return {"error": f"Scenario with ID {scenario_id} not found"}

            # Extract scenario information
            scenario_doc = scenario_details.get("scenario", {})
            scenario_description = scenario_doc.get("description", "")
            documents = scenario_details.get("documents", [])

            # If document_ids provided, filter to only those documents
            if document_ids:
                documents = [d for d in documents if d.get(
                    "id") in document_ids]

            # Build input for the agent
            agent_input = {
                "scenario_id": scenario_id,
                "automation_id": automation_id,
                "scenario_description": scenario_description
            }

            # If we have documents, use the first one for extraction
            if documents:
                document = documents[0]
                agent_input["document_id"] = document.get("id")
                agent_input["document_type"] = document.get("type")

                # Try to download document content
                try:
                    file_content = s3_download(document.get("minio_key"))
                    agent_input["content"] = file_content.decode('utf-8')
                    agent_input["filename"] = document.get("minio_key")
                except Exception as e:
                    logger.error(f"Error downloading document: {e}")

            agent_input["input"] = f"Execute scenario {scenario_id} with automation_id {automation_id}"

            logging.info(
                f"Agent input: {json.dumps(agent_input, indent=2)}")

            # Execute the agent
            logger.info(f"Agent input: {json.dumps(agent_input, indent=2)}")
            result = self.agent_executor.invoke(agent_input)
            logger.info(f"Agent result: {json.dumps(result, indent=2)}")

            # Update automation status
            drv.update_automation_status(
                automation_id=automation_id,
                statut="terminé",
                resultat=json.dumps(result),
                duree_ms=int((datetime.now() - datetime.now()
                              ).total_seconds() * 1000)
            )

            return result
        except Exception as e:
            logger.error(f"Error running agent: {e}", exc_info=True)
            # Update automation status with error
            try:
                drv = Neo4jDriver()
                drv.update_automation_status(
                    automation_id=automation_id,
                    statut="échoué",
                    resultat=str(e),
                )
            except Exception:
                pass
            return {"error": str(e), "traceback": traceback.format_exc()}


# Create a singleton instance of the agent
agent_instance = AutomationAgent()

# Export for backward compatibility
action_planning_prompt = agent_instance.prompt
agent_executor = agent_instance.agent_executor

# Export run_agent_tool for API use


def run_agent_tool(scenario_id: str, automation_id: str, document_ids: List[str] = None) -> Dict[str, Any]:
    """Wrapper for backward compatibility"""
    return agent_instance.run(scenario_id, automation_id, document_ids)
