import base64
from datetime import datetime
from typing import Any, List, Dict, Union
from PyPDF2 import PdfReader
from jinja2 import Template
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from pdf2image import convert_from_bytes
import pytesseract
import io
import csv
import json
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from langchain.schema import HumanMessage
from langchain.prompts import PromptTemplate
from langchain_groq import ChatGroq
from src.config import Config as settings
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
from pathlib import Path

logger = logging.getLogger(__name__)
# Extraction prompt
data_dir = Path(__file__).parent.parent / 'data'
PROMPT_EXTRACTION = (
    data_dir / 'prompt_extraction.md').read_text(encoding='utf-8')


class LLMTool:
    def __init__(self, model: str, temperature: float = 0.0):
        self.client = ChatGroq(api_key=settings.LLM_API_KEY,
                               model=model, temperature=temperature)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type(Exception), reraise=True)
    def invoke(self, messages: List[HumanMessage]) -> str:
        return self.client.invoke(messages).content


llm_extractor = LLMTool(settings.LLM_EXTRACTION, temperature=0.0)
llm_generator = LLMTool(settings.LLM_GENARATION)

# Text extraction


def extract_text(filename: str, content: bytes) -> str:
    ext = filename.lower().rsplit('.', 1)[-1]
    if ext == 'pdf':
        reader = PdfReader(io.BytesIO(content))
        text = ''.join(p.extract_text() or '' for p in reader.pages)
        if text.strip():
            return text
        images = convert_from_bytes(content)
        return '\n'.join(pytesseract.image_to_string(img) for img in images)
    if ext in ('txt', 'csv'):
        return content.decode('utf-8', errors='ignore')
    return content.decode('utf-8', errors='ignore')

# JSON parser


def safe_parse_json(raw: str) -> Dict[str, Any]:
    """
    Parse une chaîne brute en JSON de manière sécurisée avec un fallback.

    Args:
        raw (str): Réponse brute du LLM

    Returns:
        Dict[str, Any]: JSON parsé ou dictionnaire d'erreur si échec
    """
    try:
        # Nettoyer la réponse et tenter un parsing direct
        clean = raw.strip().strip('```json').strip('```')
        return json.loads(clean)
    except json.JSONDecodeError:
        # Rechercher un bloc JSON valide entre { et }
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and start < end:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
        # En cas d'échec, logger l'erreur et retourner un fallback
        logger.error(f"Échec du parsing JSON : {raw}")
        return {"error": "Réponse JSON invalide", "raw_response": raw}

# Tools implementations


def extract_variables(content: str) -> Dict[str, Any]:
    # Sécurise le type de content
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='ignore')
    elif not isinstance(content, str):
        content = str(content)
    # S'assure que content n'est pas un tuple ou une séquence
    if isinstance(content, (tuple, list)):
        content = "\n".join(str(x) for x in content)
    tpl = PROMPT_EXTRACTION
    prompt = PromptTemplate(
        input_variables=['text'],
        template=tpl
    ).format(text=content)
    try:
        raw = llm_extractor.invoke([HumanMessage(content=prompt)])
        logging.debug(f"Raw response: {raw}")
        res = safe_parse_json(raw)
    except Exception as e:
        logger.error(f"Error extracting variables: {e}")
        res = {}
    return res


def generate_from_template(template: str, variables: Dict[str, Any]) -> str:
    return Template(template).render(**variables)


def submit_form(url: str, data: Dict[str, Any], timeout: int = settings.WEB_TIMEOUT) -> Dict[str, Any]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=timeout)
            for sel, val in data.items():
                page.fill(sel, str(val))
            page.click('button[type=submit]')
            page.wait_for_load_state('networkidle')
            url = page.url
            browser.close()
            return {'status': 'success', 'url': url}
    except PlaywrightTimeoutError:
        return {'status': 'timeout'}
    except Exception as e:
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

def check_date_proximity(date_debut: str, date_fin: str) -> bool:
    debut = datetime.fromisoformat(date_debut)
    fin = datetime.fromisoformat(date_fin)
    return (fin - debut).days <= 30

# --- Neo4j Cypher tools ---


def run_cypher(query: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    Run a Cypher query on Neo4j. Accepts:
    - raw Cypher string with optional params
    - dict or JSON string payload {"query":..., "params":...}
    """
    query_str = None
    params_dict = params or {}
    # Handle payload as dict or JSON string
    if isinstance(query, dict):
        query_str = query.get("query")
        params_dict = query.get("params", {})
    elif isinstance(query, str) and query.strip().startswith("{"):
        try:
            payload = json.loads(query)
            query_str = payload.get("query")
            params_dict = payload.get("params", {})
        except Exception:
            logger.warning("run_cypher payload parsing failed, using raw query")
            query_str = query
    else:
        query_str = query
    try:
        drv = Neo4jDriver(
            uri=settings.get_neo4j_uri(),
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD
        )
        results = drv._run_tx(query_str, params_dict)
        drv.close()
        return results
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


def generate_pdf(html: str) -> str:
    """Generate a PDF from HTML"""
    try:
        import pdfkit
        pdf_bytes = pdfkit.from_string(html, False)
        return base64.b64encode(pdf_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return ""

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
        logger.error(
            f"Erreur lors de la sauvegarde du résultat: {e}", exc_info=True)
        return {"error": str(e)}


def create_variable(nom: str, valeur: str) -> str:
    """Crée un nœud Variable dans Neo4j et retourne son ID."""
    query = (
        "CREATE (v:Variable {nom: $nom, valeur: $valeur}) "
        "RETURN id(v) as id"
    )
    result = run_cypher(query, {"nom": nom, "valeur": valeur})
    return str(result[0]["id"]) if result else None
