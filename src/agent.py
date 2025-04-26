"""
Agent IA multi-outils orchestré avec LangChain pour l'automatisation de scénarios métier.
Utilise Groq Cloud comme LLM principal.
"""
from langchain.agents import initialize_agent, Tool
from langchain.llms import Groq
from src.tools.tools import (
    extract_variables_from_document,
    generate_email,
    fill_html_template,
    submit_web_form
)
from src.config import config as settings

# Initialisation du LLM Groq Cloud
llm = Groq(
    api_key=settings.LLM_API_KEY,
    model=settings.LLM_MODEL
)

# Définition des outils accessibles par l'agent
TOOLS = [
    Tool(
        name="extract_variables",
        func=extract_variables_from_document,
        description="Extraction de variables clés à partir d'un document brut."
    ),
    Tool(
        name="generate_email",
        func=generate_email,
        description="Génération d'un email à partir de variables et d'un template."
    ),
    Tool(
        name="fill_html_template",
        func=fill_html_template,
        description="Remplissage d'un template HTML ou texte avec des variables."
    ),
    Tool(
        name="submit_web_form",
        func=submit_web_form,
        description="Soumission automatisée d'un formulaire web."
    )
]

# Initialisation de l'agent multi-outils
agent = initialize_agent(
    tools=TOOLS,
    llm=llm,
    agent="zero-shot-react-description",
    verbose=True
)

def run_agent_tool(tool_name: str, *args, **kwargs):
    """
    Exécute un outil spécifique via l'agent IA.
    Args:
        tool_name: nom de l'outil à utiliser.
        *args, **kwargs: arguments à passer à la fonction outil.
    Returns:
        Résultat de l'outil.
    """
    for tool in TOOLS:
        if tool.name == tool_name:
            return tool.func(*args, **kwargs)
    raise ValueError(f"Outil {tool_name} non trouvé.")
