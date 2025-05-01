# src/agent_tools.py
import io
import csv
import json
import logging
from typing import Any, Dict, List, Union, Optional
import traceback

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
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
from pathlib import Path

logger = logging.getLogger(__name__)

# Charger le prompt d'extraction depuis un fichier markdown
DATA_DIR = Path(__file__).parent.parent / 'data'
PROMPT_EXTRACTION = (
    DATA_DIR / 'prompt_extraction.md').read_text(encoding='utf-8')

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

# --- Outil d'extraction de variables ---


def extract_variables(content: bytes, filename: str) -> Dict[str, Any]:
    text = extract_text(filename, content)
    # utiliser le prompt depuis le fichier
    tpl = PROMPT_EXTRACTION
    prompt = PromptTemplate(
        input_variables=['text'],
        template=tpl
    ).format(text=text)
    raw = llm_extractor.invoke([HumanMessage(content=prompt)])
    res = safe_parse_json(raw)

    return res
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

# --- S3/MinIO tools ---


def s3_upload(content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    """Upload a file to MinIO"""
    try:
        cfg = settings.get_minio_config()
        mgr = MinioManager(**cfg)
        return mgr.upload_file(content, filename, content_type)
    except Exception as e:
        logger.error(f"S3 upload error: {e}")
        return {"error": str(e)}


def s3_download(filename: str) -> bytes:
    """Download a file from MinIO"""
    try:
        cfg = settings.get_minio_config()
        mgr = MinioManager(**cfg)
        data = mgr.download_file(filename)
        return data.read()
    except Exception as e:
        logger.error(f"S3 download error: {e}")
        raise

# --- Neo4j Cypher tools ---


def run_cypher(query: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Run a Cypher query on Neo4j"""
    try:
        drv = Neo4jDriver(
            uri=settings.get_neo4j_uri(),
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD
        )
        results = drv._run_tx(query, params or {})
        drv.close()
        return results  # déjà list[dict] dans _run_tx
    except Exception as e:
        logger.error(f"Cypher query error: {e}")
        return [{"error": str(e)}]


def link_variable_to_document(document_id: str, variable_id: str) -> list:
    """Link an existing variable node to a document node in Neo4j"""
    query = (
        "MATCH (d:Document {id: $did}), (v:Variable {id: $vid}) "
        "MERGE (d)-[:HAS_VARIABLE]->(v)"
    )
    return run_cypher(query, {"did": document_id, "vid": variable_id})


def link_scenario_to_variable(scenario_id: str, variable_id: str) -> list:
    """Link an existing variable node to a scenario node in Neo4j"""
    query = (
        "MATCH (s:Scenario {id: $sid}), (v:Variable {id: $vid}) "
        "MERGE (s)-[:USES_VARIABLE]->(v)"
    )
    return run_cypher(query, {"sid": scenario_id, "vid": variable_id})

# --- PDF generation tool ---


def generate_pdf(html: str) -> bytes:
    """Generate a PDF from HTML"""
    try:
        import pdfkit
        return pdfkit.from_string(html, False)
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return b""

# --- Outil de sauvegarde des résultats générés ---
def save_generated_result(
    content: bytes,
    filename: str,
    titre: str,
    automatisation_id: str, 
    scenario_id: str,
    content_type: str = "application/octet-stream",
    type_resultat: str = "document",
    variables_utilisees: List[str] = None,
    metadonnees: Dict[str, Any] = None
) -> Dict[str, str]:
    """
    Sauvegarde un résultat généré dans MinIO et crée un nœud ResultatGenere dans Neo4j
    
    Args:
        content: Contenu du fichier à sauvegarder
        filename: Nom du fichier à sauvegarder
        titre: Titre descriptif du résultat
        automatisation_id: ID de l'automatisation
        scenario_id: ID du scénario
        content_type: Type MIME du contenu
        type_resultat: Type de résultat (document, email, pdf...)
        variables_utilisees: Liste des IDs des variables utilisées
        metadonnees: Métadonnées supplémentaires
        
    Returns:
        Dict avec l'ID du résultat généré et la clé MinIO
    """
    try:
        # Étape 1: Upload du fichier dans MinIO
        cfg = settings.get_minio_config()
        mgr = MinioManager(**cfg)
        minio_result = mgr.upload_file(content, filename, content_type)
        
        if "error" in minio_result:
            return {"error": f"Erreur lors de l'upload dans MinIO: {minio_result['error']}"}
        
        minio_key = filename
        
        # Étape 2: Création du nœud ResultatGenere dans Neo4j
        drv = Neo4jDriver(
            uri=settings.get_neo4j_uri(),
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD
        )
        
        resultat_id = drv.create_resultat_genere(
            titre=titre,
            minio_key=minio_key,
            automatisation_id=automatisation_id,
            scenario_id=scenario_id,
            type_resultat=type_resultat,
            variables_utilisees=variables_utilisees,
            metadonnees=metadonnees
        )
        
        drv.close()
        
        return {
            "resultat_id": resultat_id,
            "minio_key": minio_key
        }
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde du résultat: {e}", exc_info=True)
        return {"error": str(e)}