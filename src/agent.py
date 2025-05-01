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
import inspect

from langchain.agents import create_react_agent, Tool, AgentExecutor
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq

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
    link_variable_to_document as link_variable_to_document_fn,
    link_scenario_to_variable as link_scenario_to_variable_fn
)
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
from src.config import Config as settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# helper to wrap tool functions and normalize inputs middleware
def _wrap_tool_input(fn):
    sig = inspect.signature(fn)
    def wrapped(*args, **kwargs):
        # 1) Unpack common keys
        for key in ("parameters", "tool_input", "action_input"):
            if key in kwargs and isinstance(kwargs[key], dict):
                return fn(**kwargs.pop(key))
        # 2) Unpack positional list
        if "args" in kwargs and isinstance(kwargs["args"], list):
            return fn(*kwargs.pop("args"))
        # 3) Single kw → positional
        if len(kwargs)==1 and len(sig.parameters)==1:
            return fn(*kwargs.values())
        return fn(*args, **kwargs)
    return wrapped


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

        try:
            action_planning_template = action_plan_md.read_text()

            # Modification ici - utiliser ChatPromptTemplate au lieu de PromptTemplate
            from langchain_core.prompts import (
                ChatPromptTemplate,
                SystemMessagePromptTemplate,
                HumanMessagePromptTemplate,
                MessagesPlaceholder,
            )

            # Créer un prompt de chat plus approprié
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", action_planning_template),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}"),
            ])
            # Create the agent with the updated prompt
            agent = create_react_agent(
                llm=self.llm,
                tools=self.tools,
                prompt=self.prompt
            )

        except Exception as e:
            logger.error(
                f"Error initializing agent prompt: {e}", exc_info=True)
            # Fallback to a simpler prompt
            from langchain_core.prompts import ChatPromptTemplate

            self.prompt = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(
                    action_planning_template),
                HumanMessagePromptTemplate.from_template("{input}"),
                # sera une List[BaseMessage]
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            agent = create_react_agent(
                llm=self.llm,
                tools=self.tools,
                prompt=self.prompt
            )

        # Initialize the agent executor with better error handling
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=10
        )

    def _create_tools(self) -> List[Tool]:
        """
        Create and return the list of tools available to the agent
        """
        # wrap each function to normalize agent inputs
        return [
            Tool(name="s3_upload", func=_wrap_tool_input(s3_upload),
                 description="Upload un objet dans MinIO"),
            # Tool(name="s3_download", func=_wrap_tool_input(s3_download),
            #      description="Télécharger un objet depuis MinIO"),
            Tool(name="run_cypher", func=_wrap_tool_input(run_cypher),
                 description="Exécuter une requête Cypher sur Neo4j"),
            Tool(name="extract_variables", func=_wrap_tool_input(extract_variables),
                 description="Extraire des variables d'un document"),
            Tool(name="generate_email", func=_wrap_tool_input(self.generate_email_tool),
                 description="Générer un email via template"),
            Tool(name="fill_template", func=_wrap_tool_input(self.fill_template_tool),
                 description="Remplir un template HTML"),
            Tool(name="submit_web_form", func=_wrap_tool_input(submit_form),
                 description="Soumission de formulaire web"),
            Tool(name="generate_pdf", func=_wrap_tool_input(generate_pdf),
                 description="Générer un PDF à partir de HTML"),
            Tool(name="save_generated_result", func=_wrap_tool_input(self.save_generated_result_tool),
                 description="Sauvegarder un résultat généré (document, PDF, etc.) dans MinIO et Neo4j"),
            Tool(name="link_variable_to_document", func=_wrap_tool_input(self.link_variable_to_document_tool),
                 description="Lier une variable existante à un document Neo4j"),
            Tool(name="link_scenario_to_variable", func=_wrap_tool_input(self.link_scenario_to_variable_tool),
                 description="Lier une variable existante à un scénario Neo4j"),
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
                    agent_input["file_content"] = file_content.decode(
                        "utf-8", errors="ignore")
                    agent_input["filename"] = document.get("minio_key")
                except Exception as e:
                    logger.error(f"Error downloading document: {e}")

            agent_input["input"] = f"Execute scenario {scenario_id} with automation_id {automation_id}"
            # Execute the agent
            result = self.agent_executor.invoke(agent_input)

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
