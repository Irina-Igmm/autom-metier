"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme client principal.
"""

import logging
import json
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Type
from pathlib import Path
import base64

from src.config import config as settings

from langchain.agents import create_structured_chat_agent, AgentExecutor
from langchain_core.output_parsers import StrOutputParser

from langchain_core.tools import StructuredTool
from langchain_groq import ChatGroq
# from langchain_openai import ChatOpenAI

from pydantic import BaseModel, Field

# Import tools from the tools module
from src.neo4j_driver import Neo4jDriver
from src.tools.tools import (
    check_date_proximity,
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Modèles Pydantic pour les entrées des outils


class CheckDateProximityInput(BaseModel):
    date_debut: str
    date_fin: str


class ExtractVariablesInput(BaseModel):
    content: str = Field(default="", description="the file content")
    filename: Optional[str] = None


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


class CheckDuplicateInvoiceInput(BaseModel):
    num_facture: str
    document_id: Optional[str] = None


class CreateAndLinkVariableToDocumentInput(BaseModel):
    document_id: str
    variable_nom: str
    variable_valeur: Any
    variable_type: str = "string"
    methode: str = "IA"
    confiance: float = 1.0


# Fonctions wrapper pour les outils : chaque fonction accepte un unique objet d'entrée (input_data)

def tool_check_date_proximity(input_data: CheckDateProximityInput) -> bool:
    return check_date_proximity(input_data.date_debut, input_data.date_fin)


def tool_extract_variables(input_data: ExtractVariablesInput) -> Dict[str, Any]:
    return extract_variables(input_data.content)


def tool_s3_upload(input_data: S3UploadInput) -> Dict[str, Any]:
    content_bytes = base64.b64decode(input_data.content)
    return s3_upload(content_bytes, input_data.filename, input_data.content_type)


def tool_save_generated_result(input_data: SaveGeneratedResultInput) -> Dict[str, str]:
    try:
        from binascii import Error as BinasciiError
        try:
            content_bytes = base64.b64decode(input_data.content, validate=True)
        except (BinasciiError, ValueError):
            content_bytes = input_data.content.encode('utf-8')
        return save_generated_result(
            content_bytes,
            input_data.filename,
            input_data.titre,
            input_data.automatisation_id,
            input_data.scenario_id,
            input_data.content_type,
            input_data.type_resultat,
            input_data.variables_utilisees,
            input_data.metadonnees,
        )
    except Exception as e:
        logger.error(f"Erreur dans tool_save_generated_result: {str(e)}")
        return {"error": str(e), "traceback": traceback.format_exc()}


def tool_run_cypher(input_data: RunCypherInput) -> List[Dict[str, Any]]:
    return run_cypher(input_data.query, input_data.params)


def tool_submit_web_form(input_data: SubmitWebFormInput) -> Dict[str, Any]:
    return submit_form(input_data.url, input_data.data, input_data.timeout)


def tool_generate_pdf(input_data: GeneratePdfInput) -> str:
    return generate_pdf(input_data.html)


def tool_create_variable(input_data: CreateVariableInput) -> str:
    return create_variable(input_data.nom, input_data.valeur)


def tool_check_duplicate_invoice(input_data: CheckDuplicateInvoiceInput) -> bool:
    return Neo4jDriver().check_duplicate_invoice(
        input_data.num_facture,
        input_data.document_id
    )


def tool_generate_email(input_data: GenerateEmailInput) -> str:
    return generate_from_template(input_data.template, input_data.variables)


def tool_fill_template(input_data: FillTemplateInput) -> str:
    return generate_from_template(input_data.template, input_data.variables)


def tool_create_and_link_variable_to_document(input_data: CreateAndLinkVariableToDocumentInput) -> str:
    return Neo4jDriver().create_and_link_variable_to_document(
        input_data.document_id,
        input_data.variable_nom,
        input_data.variable_valeur,
        input_data.variable_type,
        input_data.methode,
        input_data.confiance
    )


class AutomationAgent:
    """
    Class to handle the automation agent and its tools
    """

    def __init__(self, api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL):
        """
        Initialize the agent with the necessary components
        """
        self.tools = self._create_tools()

        self.llm = ChatGroq(
            model="model,
            temperature=0.1,
            max_tokens=None,
            timeout=None,
            max_retries=2,
        )(

        # Load prompt from external markdown
        action_plan_md=Path(__file__).parent / 'data' / 'action_planning.md'

        action_planning_template=action_plan_md.read_text()

        # Créer un prompt de chat plus approprié
        from langchain_core.prompts import ChatPromptTemplate

        self.prompt=ChatPromptTemplate.from_messages([
            ("system", action_planning_template),
            ("human", "{input}"),
            ("ai", "{agent_scratchpad}"),
        ])
        # Create the agent with the updated prompt
        agent=create_structured_chat_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt,
        )

        # Initialize the agent executor with better error handling
        self.agent_executor=AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=self.tools,
            verbose=True,
            output_parser=StrOutputParser(),
            handle_parsing_errors=True,
            max_iterations=10,
            on_parsing_errors="fix_and_parse"
        )

    def _create_tools(self) -> list[StructuredTool]:
        """
        Create and return the list of tools available to the agent
        """
        return [
            StructuredTool.from_function(
                func=tool_check_date_proximity,
                name="check_date_proximity",
                description="Vérifier si la différence entre deux dates est inférieure à 30 jours. Format d'entrée: JSON {\"date_debut\": \"YYYY-MM-DD\", \"date_fin\": \"YYYY-MM-DD\"}",
                args_schema=CheckDateProximityInput,
            ),
            StructuredTool.from_function(
                func=tool_extract_variables,
                name="extract_variables",
                description="Extraire des variables d'un document. Paramètres: content (str), filename (str, optionnel)",
                args_schema=ExtractVariablesInput,
            ),
            StructuredTool.from_function(
                func=tool_s3_upload,
                name="s3_upload",
                description="Upload un objet dans MinIO. Paramètres: content (str, base64 encoded), filename (str), content_type (str)",
                args_schema=S3UploadInput,
            ),
            StructuredTool.from_function(
                func=tool_run_cypher,
                name="run_cypher",
                description="Exécuter une requête Cypher sur Neo4j. Paramètres: query (str), params (dict, optionnel)",
                args_schema=RunCypherInput,
            ),
            StructuredTool.from_function(
                func=tool_generate_email,
                name="generate_email",
                description="Générer un email via template. Paramètres: template (str), variables (dict)",
                args_schema=GenerateEmailInput,
            ),
            StructuredTool.from_function(
                func=tool_fill_template,
                name="fill_template",
                description="Remplir un template HTML. Paramètres: template (str), variables (dict)",
                args_schema=FillTemplateInput,
            ),
            StructuredTool.from_function(
                func=tool_submit_web_form,
                name="submit_web_form",
                description="Soumission de formulaire web. Paramètres: url (str), data (dict), timeout (int, optionnel)",
                args_schema=SubmitWebFormInput,
            ),
            StructuredTool.from_function(
                func=tool_generate_pdf,
                name="generate_pdf",
                description="Générer un PDF à partir de HTML. Paramètres: html (str)",
                args_schema=GeneratePdfInput,
            ),
            StructuredTool.from_function(
                func=tool_save_generated_result,
                name="save_generated_result",
                description="Sauvegarder un résultat généré dans MinIO et Neo4j. Paramètres: content (str, base64 encoded), filename (str), titre (str), automatisation_id (str), scenario_id (str), content_type (str, optionnel), type_resultat (str, optionnel), variables_utilisees (list of str, optionnel), metadonnees (dict, optionnel)",
                args_schema=SaveGeneratedResultInput,
            ),
            StructuredTool.from_function(
                func=self.link_scenario_to_variable_tool,
                name="link_scenario_to_variable",
                description="Lier une variable existante à un scénario Neo4j. Paramètres: scenario_id (str), variable_id (str)",
                args_schema=LinkScenarioToVariableInput,
            ),
            StructuredTool.from_function(
                func=tool_check_duplicate_invoice,
                name="check_duplicate_invoice",
                description="Vérifier l'existence d'une facture dans Neo4j. Paramètres: num_facture (str), document_id (str, optionnel)",
                args_schema=CheckDuplicateInvoiceInput,
            ),
            StructuredTool.from_function(
                func=tool_create_and_link_variable_to_document,
                name="create_and_link_variable_to_document",
                description=(
                    "Créer un noeud Variable et le lier à un Document dans Neo4j. "
                    "Paramètres: document_id (str), variable_nom (str), variable_valeur (Any), "
                    "variable_type (str, optionnel), methode (str, optionnel), confiance (float, optionnel)"
                ),
                args_schema=CreateAndLinkVariableToDocumentInput,
            ),
        ]

    # Simple wrapper methods to maintain API compatibility

    def save_generated_result_tool(self,
                                   content: bytes,
                                   filename: str,
                                   titre: str,
                                   automatisation_id: str,
                                   scenario_id: str,
                                   content_type: str="application/octet-stream",
                                   type_resultat: str="document",
                                   variables_utilisees: List[str]=None,
                                   metadonnees: Dict[str, Any]=None) -> Dict[str, str]:
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

    def run(self, scenario_id: str, automation_id: str, document_ids: List[str]=None) -> Dict[str, Any]:
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
            drv=Neo4jDriver()
            scenario_details=drv.get_scenario_with_relations(scenario_id)

            if not scenario_details:
                return {"error": f"Scenario with ID {scenario_id} not found"}

            # Extract scenario information
            scenario_doc=scenario_details.get("scenario", {})
            scenario_description=scenario_doc.get("description", "")
            documents=scenario_details.get("documents", [])

            # If document_ids provided, filter to only those documents
            if document_ids:
                documents=[d for d in documents if d.get(
                    "id") in document_ids]

            # Build input for the agent
            agent_input={
                "scenario_id": scenario_id,
                "automation_id": automation_id,
                "scenario_description": scenario_description
            }

            # If we have documents, use the first one for extraction
            if documents:
                document=documents[0]
                agent_input["document_id"]=document.get("id")
                agent_input["document_type"]=document.get("type")

                # Try to download document content
                try:
                    downloaded=s3_download(document.get("minio_key"))
                    text_content=downloaded.decode(
                        "utf-8", errors="ignore") if isinstance(downloaded, (bytes, bytearray)) else str(downloaded)
                    agent_input["content"]=text_content
                    agent_input["filename"]=document.get("minio_key")
                except Exception as e:
                    logger.error(f"Error downloading document: {e}")

            agent_input["input"]=f"Execute scenario {scenario_id} with automation_id {automation_id}"

            logging.info(
                f"Agent input: {json.dumps(agent_input, indent=2)}")

            # Execute the agent
            logger.info(f"Agent input: {json.dumps(agent_input, indent=2)}")
            result=self.agent_executor.invoke(agent_input)
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
                drv=Neo4jDriver()
                drv.update_automation_status(
                    automation_id=automation_id,
                    statut="échoué",
                    resultat=str(e),
                )
            except Exception:
                pass
            return {"error": str(e), "traceback": traceback.format_exc()}


# Create a singleton instance of the agent
agent_instance=AutomationAgent()

# Export for backward compatibility
action_planning_prompt=agent_instance.prompt
agent_executor=agent_instance.agent_executor

# Export run_agent_tool for API use


def run_agent_tool(scenario_id: str, automation_id: str, document_ids: List[str]=None) -> Dict[str, Any]:
    """Wrapper for backward compatibility"""
    return agent_instance.run(scenario_id, automation_id, document_ids)
