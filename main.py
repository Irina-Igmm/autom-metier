# main.py
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, UploadFile, File
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from src.models import Scenario, Variable, Automatisation
from src.neo4j_driver import Neo4jDriver
from scripts.minio_manager import MinioManager
import logging

from src.config import config

# 1. Chargement des variables d’environnement
from dotenv import load_dotenv
load_dotenv()  # lit .env à la racine

# 2. Initialisation
app = FastAPI()
logger = logging.getLogger(__name__)
logging.basicConfig(level=config.LOG_LEVEL)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/generate-token")


def get_driver() -> Neo4jDriver:
    neo4j_driver = Neo4jDriver()
    return neo4j_driver


def get_minio_manager() -> MinioManager:
    return MinioManager(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        bucket=config.MINIO_BUCKET,
        secure=config.MINIO_SECURE,
    )

@app.post("/generate-token/", summary="Génère un JWT valide 1 h")
def generate_token():
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": config.VAR_SYS,
        "exp": expire
    }
    token = jwt.encode(
        payload, config.VAR_SYS, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_at": expire.isoformat()}

# 4. Dépendance pour valider le token


def verify_token(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, config.VAR_SYS, algorithms=["HS256"])
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
            variables=[{"nom": v.key, "type": v.data_type}
                       for v in scenario.variables],
        )
        for doc_id in scenario.documents:
            driver.link_scenario_to_document(scenario_id, doc_id)
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
                    filename=doc["nom"],
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
    minio_manager: MinioManager = Depends(get_minio_manager),
    file: UploadFile = File(...),
):
    content = await file.read()
    result = minio_manager.upload_file(
        content, file.filename, file.content_type)
    return {"filename": file.filename, "bucket": result["bucket"]}


@app.get("/download/{filename}", dependencies=[Depends(verify_token)])
def download_file(
    filename: str,
    minio_manager: MinioManager = Depends(get_minio_manager)
):
    file_obj = minio_manager.download_file(filename)
    return StreamingResponse(file_obj, media_type="application/octet-stream")


@app.post("/variables/", dependencies=[Depends(verify_token)])
def create_variable(
    variable: Variable,
    driver: Neo4jDriver = Depends(get_driver),
):
    try:
        variable_id = driver.link_variable_to_document(
            document_id=variable.id,
            variable_nom=variable.key,
            variable_valeur=variable.value,
            variable_type=variable.data_type
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
