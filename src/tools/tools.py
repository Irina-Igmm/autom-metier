"""
Outils pour l'automatisation de scénarios métier pilotée par un agent IA.
Chaque fonction représente un outil accessible par l'agent multi-outils.
"""

from langchain.llms import Groq
from src.config import Config as settings
from langchain.prompts import PromptTemplate
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Initialisation du LLM Groq Cloud (modèle Llama-2 pour extraction, Mistral pour génération)
llm_extraction = Groq(api_key=settings.LLM_API_KEY, model="llama2-70b-4096")
llm_generation = Groq(api_key=settings.LLM_API_KEY, model="mixtral-8x7b-32768")

from jinja2 import Template

# Extraction de variables depuis un document via LLM avec PromptTemplate


def extract_variables_from_document(content: bytes) -> dict:
    """
    Extrait les variables clés du document en utilisant un LLM (Llama-2 via Groq Cloud).
    Args:
        content: le contenu brut du document en bytes (ex. PDF, texte).
    Returns:
        Dictionnaire des variables extraites.
    """
    text = content.decode(errors="ignore")
    prompt_template = PromptTemplate(
        input_variables=["text"],
        template=(
            "Tu es un assistant d'automatisation. Extrait les variables clés (ex: montant, fournisseur, date) du texte suivant et retourne un dictionnaire JSON.\n"
            "Texte:\n{text}\n"
            "Réponds uniquement par un JSON."
        ),
    )
    prompt = prompt_template.format(text=text)
    response = llm_extraction(prompt)
    try:
        import json

        return json.loads(response)
    except Exception:
        return {"raw": response}


# Génération d'un email à partir de variables et d'un template via LLM avec PromptTemplate


def generate_email(variables: dict, template: str) -> str:
    """
    Génère le contenu d'un email en remplissant un template avec les variables fournies, via LLM (Mixtral via Groq Cloud).
    Args:
        variables: dictionnaire des variables à injecter dans le template.
        template: chaîne de caractères contenant des placeholders (ex: {client_name}).
    Returns:
        Le texte de l'email généré.
    """
    prompt_template = PromptTemplate(
        input_variables=["template", "variables"],
        template=(
            "Tu es un assistant qui génère des emails professionnels. Remplis le template suivant avec les variables fournies.\n"
            "Template:\n{template}\n"
            "Variables:\n{variables}\n"
            "Retourne uniquement le texte de l'email généré."
        ),
    )
    prompt = prompt_template.format(template=template, variables=variables)
    return llm_generation(prompt)


# Remplissage de template HTML avec Jinja2


def fill_html_template(template: str, variables: dict) -> str:
    """
    Remplissage d'un template HTML ou texte avec les variables fournies (Jinja2).
    Args:
        template: contenu HTML/textuel avec placeholders Jinja2 (ex: {{ client_name }}).
        variables: dictionnaire des valeurs à injecter.
    Returns:
        Le contenu généré.
    """
    return Template(template).render(**variables)


# Soumission automatisée de formulaire web (simulation)
def submit_web_form(url: str, form_data: dict) -> dict:
    """
    Soumet un formulaire web de manière automatisée avec Playwright.
    Args:
        url: URL de la page contenant le formulaire.
        form_data: dictionnaire champ->valeur (les clés sont les noms ou sélecteurs CSS des champs).
    Returns:
        Statut de la soumission et URL de confirmation ou message d'erreur.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20000)
            for field, value in form_data.items():
                # On suppose que 'field' est un sélecteur CSS ou le nom du champ
                try:
                    page.fill(f'input[name="{field}"]', str(value))
                except PlaywrightTimeoutError:
                    return {"status": "error", "message": f"Champ {field} introuvable"}
            # Soumettre le formulaire (on suppose qu'il y a un bouton de type submit)
            page.click('input[type="submit"], button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=10000)
            confirmation_url = page.url
            browser.close()
            return {"status": "success", "confirmation_url": confirmation_url}
    except Exception as e:
        return {"status": "error", "message": str(e)}


"""
# Documentation des choix LLM :
# - Extraction de variables : Llama-2-70B (Groq Cloud) pour sa capacité à comprendre le texte métier, coût modéré, open-source.
# - Génération d'email : Mixtral-8x7B (Groq Cloud) pour la génération de texte naturel, coût/latence optimisés.
# - Template HTML : Jinja2 (open-source, local, rapide).
# - Soumission web : Playwright/Selenium (non LLM, à intégrer si besoin réel).
"""
