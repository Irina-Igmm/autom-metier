"""
Outils pour l'automatisation de scénarios métier pilotée par un agent IA.
Chaque fonction représente un outil accessible par l'agent multi-outils.
"""

import io
import csv
from langchain_groq import ChatGroq
from src.config import Config as settings
from langchain.prompts import PromptTemplate
from langchain.schema import HumanMessage
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from jinja2 import Template

from PyPDF2 import PdfReader
import logging

# Initialisation du LLM Groq Cloud (modèle Llama-2 pour extraction, Mistral pour génération)
llm_extraction = ChatGroq(
    api_key=settings.LLM_API_KEY, model="meta-llama/llama-4-scout-17b-16e-instruct", temperature=0.0)
llm_generation = ChatGroq(api_key=settings.LLM_API_KEY, model="mixtral-8x7b-32768")


# Extraction de variables depuis un document via LLM avec PromptTemplate


def extract_text_from_bytes(filename: str, content: bytes) -> str:
    """
    Extrait le texte brut selon le type de document.
    Supporte .txt, .pdf, .csv.
    """
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "txt":
        return content.decode(errors="ignore")
    elif ext == "pdf":
        reader = PdfReader(io.BytesIO(content))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    elif ext == "csv":
        text = ""
        stream = io.StringIO(content.decode(errors="ignore"))
        reader = csv.reader(stream)
        for row in reader:
            text += " ".join(row) + "\n"
        return text
    else:
        # fallback to raw decode
        return content.decode(errors="ignore")


def _parse_json_safely(content: str) -> dict:
    """
    Parse une chaîne JSON avec nettoyage et robustesse.
    Retourne toujours un dictionnaire. Si le résultat JSON n'est pas un dictionnaire,
    il sera encapsulé dans la clé "result".
    """
    if not isinstance(content, str):
        return {"error": f"Expected string but got {type(content)}", "content_type": str(type(content))}
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3].strip()
    try:
        import json
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            parsed = {"result": parsed}
        return parsed
    except json.JSONDecodeError as e:
        logging.warning(f"Erreur parsing JSON: {e}, tentative de nettoyage...")
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            try:
                parsed = json.loads(content[start_idx : end_idx + 1])
                if not isinstance(parsed, dict):
                    parsed = {"result": parsed}
                return parsed
            except Exception:
                pass
        logging.error(f"Impossible de parser le JSON: {content[:100]}...")
        return {"error": "Échec du parsing JSON", "raw": content[:500]}


def extract_variables_from_document(content: bytes, filename: str) -> dict:
    logging.info(f"[AGENT TOOL] Appel de extract_variables_from_document sur {filename}")
    text = extract_text_from_bytes(filename, content)
    logging.info(f"Extraction de variables depuis {filename}: {len(text)} caractères")
    prompt_template = PromptTemplate(
        input_variables=["text"],
        template=(
            "Tu es un assistant d'automatisation spécialisé dans l'extraction de données de documents commerciaux. "
            "Extrait toutes les variables métier utiles du texte suivant et retourne un dictionnaire JSON.\n\n"
            "Exemples de variables (si présentes) :\n"
            "- date_document: (YYYY-MM-DD)\n"
            "- numero_facture\n"
            "- nom_entreprise\n"
            "- nom_client\n"
            "- montant_ht\n"
            "- montant_ttc\n"
            "- date_echeance: (YYYY-MM-DD)\n"
            "- produits: liste d'objets (description, quantité, prix, tva, total)\n"
            "- conditions_reglement, mode_reglement, reste_a_payer, etc.\n\n"
            "Texte à analyser:\n{text}\n\n"
            "Réponds uniquement par un JSON valide sans commentaire ni formatage markdown."
        ),
    )
    prompt = prompt_template.format(text=text)
    result = llm_extraction.invoke([HumanMessage(content=prompt)])
    content_str = result.content
    parsed = _parse_json_safely(content_str)
    if "error" in parsed:
        logging.error(f"Erreur extraction LLM: {parsed['error']}")
    return parsed


# Génération d'un email à partir de variables et d'un template via LLM avec PromptTemplate


def generate_email(variables: dict, template: str) -> str:
    logging.info(f"[AGENT TOOL] Appel de generate_email avec variables: {list(variables.keys())}")
    prompt_template = PromptTemplate(
        input_variables=["template", "variables"],
        template=(
            "Tu es un assistant qui génère des emails professionnels. Remplis le template suivant "
            "avec les variables fournies.\n"
            "Template:\n{template}\n"
            "Variables:\n{variables}\n"
            "Retourne uniquement le texte de l'email généré."
        ),
    )
    prompt = prompt_template.format(template=template, variables=variables)
    response = llm_generation.invoke([HumanMessage(content=prompt)])
    return response.content


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
    logging.info(f"[AGENT TOOL] Appel de fill_html_template avec variables: {list(variables.keys())}")
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
    logging.info(f"[AGENT TOOL] Appel de submit_web_form sur {url} avec champs: {list(form_data.keys())}")

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
