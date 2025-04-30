# main.py
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, UploadFile, File, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from src.models import Scenario, Automatisation, Document as DocumentModel
from src.neo4j_driver import Neo4jDriver
from scripts.minio_manager import MinioManager
import logging
from pydantic import BaseModel
from typing import Generator

from src.config import config

# 1. Chargement des variables d’environnement
from dotenv import load_dotenv
load_dotenv()  # lit .env à la racine

# 2. Initialisation
app = FastAPI()
logger = logging.getLogger(__name__)
logging.basicConfig(level=config.LOG_LEVEL)

security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, config.SECRET_KEY or config.VAR_SYS, algorithms=["HS256"]
        )
        subject: str = payload.get("sub")
        if subject != config.VAR_SYS:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return subject


def get_driver(current_user: str = Depends(verify_token)) -> Generator[Neo4jDriver, None, None]:
    # Création du driver Neo4j pour l'utilisateur authentifié
    driver = Neo4jDriver()
    try:
        yield driver
    finally:
        driver.close()


def get_minio_manager(current_user: str = Depends(verify_token)) -> MinioManager:
    # Création du manager MinIO avec contexte utilisateur pour autorisation
    minio_conf = config.get_minio_config()
    mgr = MinioManager(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        bucket=config.MINIO_BUCKET,
        secure=config.MINIO_SECURE,
    )
    mgr.current_user = current_user
    return mgr


@app.post("/generate-token/", summary="Génère un JWT valide 1 h")
def generate_token():
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": config.VAR_SYS,
        "exp": expire
    }
    token = jwt.encode(
        payload, config.SECRET_KEY or config.VAR_SYS, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_at": expire.isoformat()}

# 4. Dépendance pour valider le token


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, config.SECRET_KEY or config.VAR_SYS, algorithms=["HS256"]
        )
        subject: str = payload.get("sub")
        if subject != config.VAR_SYS:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return subject

# 5. Endpoints protégés


@app.post("/scenarios/", dependencies=[Depends(verify_token)])
def create_scenario(
    scenario: Scenario,
    driver: Neo4jDriver = Depends(get_driver),
):
    try:
        scenario_id = driver.create_scenario(
            nom=scenario.nom,
            description=scenario.description,
            priorite=scenario.priorite,
            document_ids=scenario.documents,
            variables=[
                {"key": v.key, "data_type": v.data_type.value}
                for v in scenario.variables
            ]
        )
        return {"scenario_id": scenario_id}
    except Exception as e:
        logger.error(f"Erreur création scénario: {e}")
        raise HTTPException(status_code=500, detail="Création échouée")


@app.post("/scenarios/{scenario_id}/run", dependencies=[Depends(verify_token)])
async def run_scenario(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    driver: Neo4jDriver = Depends(get_driver),
    minio_manager: MinioManager = Depends(get_minio_manager),
    sync: bool = False,
):
    def execute():
        try:
            scenario = driver.get_scenario_with_relations(scenario_id)
            if not scenario:
                raise HTTPException(
                    status_code=404, detail="Scénario non trouvé")
            results = []
            for doc in scenario["documents"]:
                file_bytes = minio_manager.download_file(
                    doc["minio_key"]).read()
                from src.agent import create_dynamic_scenario
                agent_result = create_dynamic_scenario(
                    document_content=file_bytes,
                    filename=doc["titre"],
                    scenario_nature=scenario["nom"],
                    driver=driver,
                )
                results.append(agent_result)
            return {"status": "terminé", "results": results}
        except Exception as e:
            logger.error(f"Erreur exécution scénario {scenario_id}: {e}")
            return {"status": "échoué", "error": str(e)}

    if sync:
        return execute()
    background_tasks.add_task(execute)
    return {"status": "Automatisation lancée"}


@app.post("/upload/", dependencies=[Depends(verify_token)])
async def upload_file(
    file: UploadFile = File(...),
    type_doc: str = "autre",
    statut: str = "actif",
    minio_manager: MinioManager = Depends(get_minio_manager),
    driver: Neo4jDriver = Depends(get_driver),
):
    """Upload un fichier dans MinIO et créer un nœud Document dans Neo4j."""
    content = await file.read()
    result = minio_manager.upload_file(
        content, file.filename, file.content_type)
    neo4j_doc_id = driver.create_document(
        titre=file.filename,
        type=type_doc,
        minio_key=file.filename,
        statut=statut
    )
    result["neo4j_doc_id"] = neo4j_doc_id
    return result


@app.get("/download/{filename}", dependencies=[Depends(verify_token)])
def download_file(
    filename: str,
    minio_manager: MinioManager = Depends(get_minio_manager)
):
    file_obj = minio_manager.download_file(filename)
    return StreamingResponse(file_obj, media_type="application/octet-stream")


class VariableCreate(BaseModel):
    document_id: str
    key: str
    data_type: str
    value: str | None = None


@app.post("/variables/", dependencies=[Depends(verify_token)])
def create_variable(
    var: VariableCreate,
    driver: Neo4jDriver = Depends(get_driver),
):
    try:
        variable_id = driver.link_variable_to_document(
            document_id=var.document_id,
            variable_nom=var.key,
            variable_valeur=var.value,
            variable_type=var.data_type,
        )
        return {"variable_id": variable_id}
    except Exception as e:
        logger.error(f"Erreur création variable: {e}")
        raise HTTPException(status_code=500, detail="Création échouée")


@app.get("/variables/{variable_id}", dependencies=[Depends(verify_token)])
def get_variable(variable_id: str, driver: Neo4jDriver = Depends(get_driver)):
    try:
        query = "MATCH (v:Variable {id: $id}) RETURN v"
        with driver.driver.session() as session:
            record = session.run(query, id=variable_id).single()
            if not record:
                raise HTTPException(
                    status_code=404, detail="Variable non trouvée")
            return dict(record["v"])
    except Exception as e:
        logger.error(f"Erreur récupération variable: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne")


@app.delete("/variables/{variable_id}", dependencies=[Depends(verify_token)])
def delete_variable(variable_id: str, driver: Neo4jDriver = Depends(get_driver)):
    try:
        with driver.driver.session() as session:
            session.run(
                "MATCH (v:Variable {id: $id}) DETACH DELETE v", id=variable_id)
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Erreur suppression variable: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne")


@app.post("/automatisations/", dependencies=[Depends(verify_token)])
def create_automatisation(
    automatisation: Automatisation,
    driver: Neo4jDriver = Depends(get_driver),
):
    try:
        automatisation_id = driver.start_automation(
            scenario_id=automatisation.scenario_id,
            agent_config=automatisation.agent_config
        )
        return {"automatisation_id": automatisation_id}
    except Exception as e:
        logger.error(f"Erreur création automatisation: {e}")
        raise HTTPException(status_code=500, detail="Création échouée")


@app.get("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
def get_automatisation(automatisation_id: str, driver: Neo4jDriver = Depends(get_driver)):
    try:
        with driver.driver.session() as session:
            record = session.run(
                "MATCH (a:Automatisation {id: $id}) RETURN a", id=automatisation_id
            ).single()
        if not record:
            raise HTTPException(
                status_code=404, detail="Automatisation non trouvée")
        return dict(record["a"])
    except Exception as e:
        logger.error(f"Erreur récupération automatisation: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne")


@app.delete("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
def delete_automatisation(automatisation_id: str, driver: Neo4jDriver = Depends(get_driver)):
    try:
        with driver.driver.session() as session:
            session.run(
                "MATCH (a:Automatisation {id: $id}) DETACH DELETE a", id=automatisation_id)
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Erreur suppression automatisation: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne")


@app.post("/documents/", dependencies=[Depends(verify_token)])
def create_document(
    doc: DocumentModel,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Créer un document dans Neo4j sans upload MinIO"""
    try:
        doc_id = driver.create_document(
            titre=doc.titre,
            type=doc.type,
            minio_key=doc.minio_key,
            statut=doc.statut.value
        )
        return {"document_id": doc_id}
    except Exception as e:
        logger.error(f"Erreur création document: {e}")
        raise HTTPException(status_code=500, detail="Création échouée")


@app.get("/documents/{document_id}", dependencies=[Depends(verify_token)])
def get_document(document_id: str, driver: Neo4jDriver = Depends(get_driver)):
    """Récupérer un document par ID"""
    doc = driver.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    return doc


@app.delete("/documents/{document_id}", dependencies=[Depends(verify_token)])
def delete_document(document_id: str, driver: Neo4jDriver = Depends(get_driver)):
    """Supprimer un document et ses relations"""
    try:
        driver.delete_entity("Document", document_id)
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Erreur suppression document: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Erreur inattendue {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )
