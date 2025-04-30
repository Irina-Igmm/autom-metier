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
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
from src.config import Config as settings
from pathlib import Path

logger = logging.getLogger(__name__)

# Charger le prompt d'extraction depuis un fichier markdown
DATA_DIR = Path(__file__).parent.parent / 'data'
PROMPT_EXTRACTION = (DATA_DIR / 'prompt_extraction.md').read_text(encoding='utf-8')

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
llm_generator = LLMTool(settings.LLM_GENARATION)

# --- Extraction de texte brut ---


def extract_text(filename: str, content: bytes) -> str:
    ext = filename.lower().rsplit('.', 1)[-1]
    if ext == 'txt':
        return content.decode('utf-8', errors='ignore')
    if ext == 'pdf':
        reader = PdfReader(io.BytesIO(content))
        text = ''.join(p.extract_text() or '' for p in reader.pages)
        if text.strip():
            return text
        # fallback OCR on PDF pages
        try:
            images = convert_from_bytes(content)
            return '\n'.join(pytesseract.image_to_string(img) for img in images)
        except Exception:
            return text
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

# --- Outil d’extraction de variables ---


def extract_variables(content: bytes, filename: str) -> Dict[str, Any]:
    text = extract_text(filename, content)
    # utiliser le prompt depuis le fichier
    tpl = PROMPT_EXTRACTION
    prompt = PromptTemplate(
        input_variables=['text'],
        template=tpl
    ).format(text=text)
    raw = llm_extractor.invoke([HumanMessage(content=prompt)])
    return safe_parse_json(raw)

# --- Génération de documents et emails ---


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


# Aliases pour Agent multi-outils
extract_variables_from_document = extract_variables
generate_email = generate_from_template
fill_html_template = generate_from_template
submit_web_form = submit_form
