from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import StreamingResponse
from datetime import datetime
from src.models import Scenario
from src.neo4j_driver import neo4j_driver, Neo4jDriver
from scripts.minio_manager import MinioManager
from src.config import config
from src.agent import run_agent_tool
import logging
import time
from typing import List, Optional
from jose import JWTError, jwt
from datetime import timedelta

app = FastAPI()
logger = logging.getLogger(__name__)
logging.basicConfig(level=config.LOG_LEVEL)


def get_driver():
    return neo4j_driver


def get_minio_manager():
    minio_conf = config.get_minio_config()
    return MinioManager(
        minio_conf["endpoint"],
        minio_conf["access_key"],
        minio_conf["secret_key"],
        minio_conf["bucket"],
        secure=minio_conf["secure"],
    )


# Security setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

SECRET_KEY = config.SECRET_KEY or "changeme"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def authenticate_user(username: str, password: str):
    # TODO: replace with real authentication logic
    if username == "testuser" and password == "testpassword":
        return {"username": username}
    return None


@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": user["username"], "exp": expire}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return {"username": username}
    except JWTError:
        raise credentials_exception


@app.post("/scenarios/")
def create_scenario(
    scenario: Scenario,
    driver: Neo4jDriver = Depends(get_driver),
    current_user: dict = Depends(get_current_user),
):
    # endpoint protected by token
    try:
        # Création du nœud Scenario dans Neo4j en utilisant les champs Pydantic
        scenario_id = driver.create_scenario(
            nom=scenario.nom,
            description=scenario.description,
            priorite=scenario.priorite,
            document_ids=scenario.documents,
            variables=[{"nom": v, "type": ""} for v in scenario.variables],
        )
        # Création des liens Scenario--UTILISE-->Document (les variables sont créées et liées par create_scenario)
        for doc_id in scenario.documents:
            driver.link_scenario_to_document(scenario_id, doc_id)
        return {"scenario_id": scenario_id}
    except Exception as e:
        logger.error(f"Erreur lors de la création du scénario: {e}")
        raise HTTPException(status_code=500, detail="Impossible de créer le scénario")


# ...existing code...


@app.post("/scenarios/{scenario_id}/run")
async def run_scenario(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    driver: Neo4jDriver = Depends(get_driver),
    minio_manager: MinioManager = Depends(get_minio_manager),
    sync: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """
    Exécution automatisée d'un scénario pilotée par l'agent IA :
    1. Récupère le scénario et le(s) document(s) associé(s) depuis Neo4j/MinIO
    2. Demande à l'agent IA de générer dynamiquement le plan d'action (outils, ordre, paramètres)
    3. Exécute chaque tâche via l'agent (extraction, génération, remplissage, etc.)
    4. Met à jour Neo4j et MinIO à chaque étape
    """

    def execute():
        try:
            # 1. Récupérer le scénario et les documents associés
            scenario = driver.get_scenario_with_relations(scenario_id)
            if not scenario:
                logger.warning(f"Scénario {scenario_id} non trouvé")
                raise HTTPException(status_code=404, detail="Scenario not found")
            documents = scenario["documents"]
            results = []
            for doc in documents:
                minio_key = doc.get("minio_key") or doc.get("chemin")
                file_bytes = minio_manager.download_file(minio_key).read()
                # 2. Appel à l'agent IA pour orchestrer tout le flux
                from src.agent import create_dynamic_scenario

                agent_result = create_dynamic_scenario(
                    document_content=file_bytes,
                    filename=doc["nom"],
                    scenario_nature=scenario["nom"],
                    driver=driver,
                )
                results.append(agent_result)
            # 3. Mettre à jour le statut d'automatisation dans Neo4j
            # (optionnel: driver.update_automation_status(...))
            return {"status": "terminé", "results": results}
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution du scénario {scenario_id}: {e}")
            return {"status": "échoué", "error": str(e)}

    if sync:
        return execute()
    else:
        background_tasks.add_task(execute)
        return {"status": "Automatisation lancée"}


@app.post("/upload/", dependencies=[Depends(get_current_user)])
async def upload_file(
    minio_manager: MinioManager = Depends(get_minio_manager),
    file: UploadFile = File(...),
):
    content = await file.read()
    result = minio_manager.upload_file(content, file.filename, file.content_type)
    return {"filename": file.filename, "bucket": result["bucket"]}


@app.get("/download/{filename}", dependencies=[Depends(get_current_user)])
def download_file(
    filename: str, minio_manager: MinioManager = Depends(get_minio_manager)
):
    file_obj = minio_manager.download_file(filename)
    return StreamingResponse(file_obj, media_type="application/octet-stream")
