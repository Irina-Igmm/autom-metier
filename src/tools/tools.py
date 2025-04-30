
# src/agent_tools.py
import io
import csv
import json
import logging
from typing import Any, Dict, List, Union

from PyPDF2 import PdfReader
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from jinja2 import Template
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from langchain.schema import HumanMessage

from src.config import Config as settings

logger = logging.getLogger(__name__)

# --- Classe générique de gestion des LLM ---


class LLMTool:
    def __init__(self, model: str, temperature: float = 0.0):
        self.client = ChatGroq(
            api_key=settings.LLM_API_KEY,
            model=model,
            temperature=temperature,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4),
           retry=retry_if_exception_type(Exception), reraise=True)
    def invoke(self, messages: List[HumanMessage]) -> str:
        response = self.client.invoke(messages)
        return response.content


# Instances dédiées
llm_extractor = LLMTool(settings.LLM_EXTRACTION, temperature=0.0)
llm_generator = LLMTool(settings.LLM_GENERATION)

# --- Extraction de texte brut ---


def extract_text(filename: str, content: bytes) -> str:
    ext = filename.lower().rsplit('.', 1)[-1]
    if ext == 'txt':
        return content.decode('utf-8', errors='ignore')
    if ext == 'pdf':
        reader = PdfReader(io.BytesIO(content))
        return ''.join(p.extract_text() or '' for p in reader.pages)
    if ext == 'csv':
        stream = io.StringIO(content.decode('utf-8', errors='ignore'))
        reader = csv.reader(stream)
        return ''.join(','.join(row) for row in reader)
    # fallback
    return content.decode('utf-8', errors='ignore')

# --- Parsing JSON robuste ---


def safe_parse_json(raw: str) -> Dict[str, Any]:
    try:
        clean = raw.strip().strip('```json').strip('```')
        obj = json.loads(clean)
        return obj if isinstance(obj, dict) else {'result': obj}
    except Exception as e:
        logger.warning(f"JSON parse error: {e}")
        # tentative de nettoyage plus fine
        start, end = raw.find('{'), raw.rfind('}')
        if start != -1 < end:
            try:
                return json.loads(raw[start:end+1])
            except Exception as e:
                pass
        return {'error': 'json_parse_failed', 'raw': raw[:200]}

# --- Prompt template pour extraction robuste dans Config ---
TEMPLATE_EXTRACTION = """
You are a domain-specific data extraction assistant. Given the input document text, extract the following fields if present and return a valid JSON object containing only these keys (omit any null values):

- date_document (YYYY-MM-DD)
- numero_facture
- nom_entreprise
- nom_client
- montant_ht
- montant_ttc
- date_echeance (YYYY-MM-DD)
- produits: list of objects with keys description, quantite, prix_unitaire, tva, total
- conditions_reglement
- mode_reglement
- reste_a_payer

Ensure the output is strictly JSON, without Markdown or code fences. If a field is missing, simply omit it from the JSON. If no variables are found, return {}.

Document text:
{text}
"""
# --- Outil d’extraction de variables ---
def extract_variables(content: bytes, filename: str) -> Dict[str, Any]:
    text = extract_text(filename, content)
    prompt = PromptTemplate(
        input_variables=['text'],
        template=TEMPLATE_EXTRACTION
    ).format(text=text)
    raw = llm_extractor.invoke([HumanMessage(content=prompt)])
    return safe_parse_json(raw)

# --- Génération de documents et mails ---


def generate_from_template(template: str, variables: Dict[str, Any]) -> str:
    try:
        return Template(template).render(**variables)
    except Exception as e:
        logger.error(f"Template render error: {e}")
        raise

# --- Soumission de formulaire web ---


def submit_form(
    url: str,
    data: Dict[str, Union[str, int, float]],
    timeout: int = settings.WEB_TIMEOUT
) -> Dict[str, Any]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout)
            for sel, val in data.items():
                page.fill(sel, str(val), timeout=timeout)
            page.click('button[type=submit]', timeout=timeout)
            page.wait_for_load_state('networkidle', timeout=timeout)
            confirmation = page.url
            browser.close()
            return {'status': 'success', 'url': confirmation}
    except PlaywrightTimeoutError as e:
        logger.warning(f"Timeout form submit: {e}")
        return {'status': 'error', 'message': 'timeout'}
    except Exception as e:
        logger.exception("Form submission error")
        return {'status': 'error', 'message': str(e)}
