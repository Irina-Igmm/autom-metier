# main.py
from fastapi.encoders import jsonable_encoder
import os
from datetime import datetime, timedelta
import uuid
from contextlib import asynccontextmanager
from typing import Generator

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from pydantic import BaseModel

from src.agent import run_agent_tool, agent_executor, action_planning_prompt as prompt_template
from src.models import Scenario, Automatisation, Document as DocumentModel
from src.neo4j_driver import Neo4jDriver
from scripts.minio_manager import MinioManager
from src.tools.tools import safe_parse_json
import logging

from src.config import config

# Setup templates for dashboard
templates = Jinja2Templates(directory="templates")

# Initialize app with context manager to setup templates directory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create templates directory if it doesn't exist
    os.makedirs("templates", exist_ok=True)

    # Create static directory if it doesn't exist
    os.makedirs("static", exist_ok=True)

    yield


# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)
logger = logging.getLogger(__name__)
logging.basicConfig(level=config.LOG_LEVEL)

# Mount static files
# Ensure static directory exists before mounting
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

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


# 5. Endpoints protégés


@app.post("/scenarios/", dependencies=[Depends(verify_token)])
def create_scenario(
    scenario: Scenario,
    driver: Neo4jDriver = Depends(get_driver),
):
    # Créer des structures pour les variables et étapes attendues par Neo4j
    variables_dicts = []
    if scenario.variables:
        variables_dicts = [
            {"key": v.key, "data_type": v.data_type.value}
            for v in scenario.variables
        ]
    etapes_dicts = []
    if scenario.etapes:
        etapes_dicts = [step.dict() for step in scenario.etapes]
    scenario_id = driver.create_scenario(
        nom=scenario.nom,
        description=scenario.description,
        priorite=scenario.priorite.value,
        document_ids=scenario.documents,
        variables=variables_dicts,
        etapes=etapes_dicts
    )
    return {"scenario_id": scenario_id}


# Dashboard endpoint - accessible without authentication
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the dashboard for monitoring automation status"""
    return templates.TemplateResponse("dashboard.html", {"request": request})


# API endpoints for tasks and dashboard
@app.get("/api/tasks", response_class=JSONResponse)
async def get_tasks(token: str = None):
    """Get all tasks with their status and details
    Can be accessed without authentication for the dashboard, but requires token for sensitive details
    """
    tasks = list(getattr(run_scenario_enhanced, "tasks", {}).values())

    # If no token provided, return limited information (for dashboard)
    if not token:
        return sorted([{
            "id": t["id"],
            "type": t["type"],
            "status": t["status"],
            "created_at": t["created_at"],
            "started_at": t["started_at"],
            "completed_at": t["completed_at"],
            "progress": t["progress"]
        } for t in tasks], key=lambda x: x["created_at"], reverse=True)

    # Verify token for full details
    try:
        payload = jwt.decode(
            token, config.SECRET_KEY or config.VAR_SYS, algorithms=["HS256"])
        if payload.get("sub") != config.VAR_SYS:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Return full task details for authenticated users
    return sorted(tasks, key=lambda x: x["created_at"], reverse=True)


@app.get("/api/tasks/{task_id}", response_class=JSONResponse)
async def get_task(task_id: str, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get details of a specific task (requires authentication)"""
    task = getattr(run_scenario_enhanced, "tasks", {}).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/scenarios/{scenario_id}/run", dependencies=[Depends(verify_token)])
async def run_scenario_enhanced(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    driver: Neo4jDriver = Depends(get_driver),
    # minio_manager: MinioManager = Depends(get_minio_manager),
):
    """Trigger scenario execution asynchronously via BackgroundTasks."""
    import json
    import time
    from datetime import datetime
    # Create automation instance in Neo4j
    automation_id = driver.start_automation(
        scenario_id, agent_config=json.dumps({}))
    task_id = str(uuid.uuid4())
    # Initialize task status for dashboard
    task_status = {
        "id": task_id,
        "type": "scenario_execution",
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "started_at": None,
        "completed_at": None,
        "progress": 0,
        "logs": [],
        "result": None,
        "error": None,
        "automation_id": automation_id,
        "scenario_id": scenario_id
    }
    # Register task for dashboard tracking
    tasks_store = getattr(run_scenario_enhanced, "tasks", {})
    tasks_store[task_id] = task_status
    run_scenario_enhanced.tasks = tasks_store

    def update_task(**kwargs):
        run_scenario_enhanced.tasks[task_id].update(**kwargs)

    def log(msg, level="INFO"):
        run_scenario_enhanced.tasks[task_id]["logs"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": msg
        })

    def execute_scenario():
        update_task(status="running", started_at=datetime.utcnow().isoformat())
        start_time = time.time()
        try:
            log(f"Starting scenario execution: {scenario_id}")
            data = driver.get_scenario_with_relations(scenario_id)
            if not data:
                raise ValueError(f"Scenario not found: {scenario_id}")
            log(f"Scenario loaded: {data['scenario'].get('nom', 'Unnamed')}")
            steps = data['scenario'].get('etapes', [])
            # If no predefined steps, let the agent generate plan on the fly
            if not steps:
                log("No predefined steps: agent will create plan on the fly")
                plan_prompt = prompt_template.format(
                    scenario_id=scenario_id,
                    document_id=(data['documents'][0]['id'] if data.get('documents') else None),
                    document_type=(data['documents'][0].get('type') if data.get('documents') else None),
                    scenario_description=data['scenario'].get('description', '')
                )
                raw = agent_executor.invoke({'input': plan_prompt})
                plan = safe_parse_json(raw)
                steps = plan.get('actions', []) if isinstance(plan, dict) else []
                # Persist generated steps
                driver.update_scenario_etapes(scenario_id, steps)
            steps = sorted(steps, key=lambda e: e.get('ordre', 0))
            results = []
            for i, step in enumerate(steps):
                tool = step['outil']
                params = step.get('params', {})
                try:
                    out = run_agent_tool(tool, **params)
                    results.append({'step': i+1, 'outil': tool,
                                   'status': 'success', 'result': out})
                except Exception as ex:
                    log(f"Error in step {i+1}: {str(ex)}", level="ERROR")
                    results.append({'step': i+1, 'outil': tool,
                                   'status': 'error', 'error': str(ex)})
            duration_ms = int((time.time() - start_time) * 1000)
            driver.update_automation_status(
                automation_id=automation_id,
                statut='terminé',
                resultat=json.dumps(results),
                duree_ms=duration_ms
            )
            driver.update_scenario(
                scenario_id=scenario_id,
                statut='completed',
                resultat=json.dumps({"actions": results})
            )
            update_task(status="completed", completed_at=datetime.utcnow(
            ).isoformat(), result=results, progress=100)
        except Exception as e:
            error_msg = str(e)
            log(f"Scenario execution failed: {error_msg}", level="ERROR")
            duration_ms = int((time.time() - start_time) * 1000)
            try:
                driver.update_automation_status(
                    automation_id=automation_id,
                    statut='échoué',
                    resultat=json.dumps({'error': error_msg}),
                    duree_ms=duration_ms
                )
                driver.update_scenario(
                    scenario_id=scenario_id,
                    statut='failed',
                    resultat=json.dumps({"error": error_msg})
                )
            except Exception as update_error:
                log(f"Failed to update status: {str(update_error)}",
                    level="ERROR")
            update_task(status="failed", completed_at=datetime.utcnow(
            ).isoformat(), error=error_msg, progress=100)

    # Schedule background execution
    background_tasks.add_task(execute_scenario)
    return {
        "task_id": task_id,
        "automation_id": automation_id,
        "status": "queued",
        "message": "Task queued for execution"
    }


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
    variable_id = driver.link_variable_to_document(
        document_id=var.document_id,
        variable_nom=var.key,
        variable_valeur=var.value,
        variable_type=var.data_type,
    )
    return {"variable_id": variable_id}


@app.get("/variables/{variable_id}", dependencies=[Depends(verify_token)])
def get_variable(variable_id: str, driver: Neo4jDriver = Depends(get_driver)):
    query = "MATCH (v:Variable {id: $id}) RETURN v"
    with driver.driver.session() as session:
        record = session.run(query, id=variable_id).single()
        if not record:
            raise HTTPException(
                status_code=404, detail="Variable non trouvée")
        return dict(record["v"])


@app.delete("/variables/{variable_id}", dependencies=[Depends(verify_token)])
def delete_variable(variable_id: str, driver: Neo4jDriver = Depends(get_driver)):
    with driver.driver.session() as session:
        session.run(
            "MATCH (v:Variable {id: $id}) DETACH DELETE v", id=variable_id)
    return {"status": "deleted"}


@app.post("/automatisations/", dependencies=[Depends(verify_token)])
def create_automatisation(
    automatisation: Automatisation,
    driver: Neo4jDriver = Depends(get_driver),
):
    automatisation_id = driver.start_automation(
        scenario_id=automatisation.scenario_id,
        agent_config=automatisation.agent_config
    )
    return {"automatisation_id": automatisation_id}


@app.get("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
def get_automatisation(automatisation_id: str, driver: Neo4jDriver = Depends(get_driver)):
    with driver.driver.session() as session:
        rec = session.run(
            "MATCH (a:Automatisation {id: $id}) RETURN a", id=automatisation_id
        ).single()
    if not rec:
        raise HTTPException(
            status_code=404, detail="Automatisation non trouvée")
    node = dict(rec["a"])
    # jsonable_encoder va transformer dateExecution en chaîne ISO
    return JSONResponse(content=jsonable_encoder(node))


@app.delete("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
def delete_automatisation(automatisation_id: str, driver: Neo4jDriver = Depends(get_driver)):
    with driver.driver.session() as session:
        session.run(
            "MATCH (a:Automatisation {id: $id}) DETACH DELETE a", id=automatisation_id)
    return {"status": "deleted"}


@app.post("/documents/", dependencies=[Depends(verify_token)])
def create_document(
    doc: DocumentModel,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Créer un document dans Neo4j sans upload MinIO"""
    doc_id = driver.create_document(
        titre=doc.titre,
        type=doc.type,
        minio_key=doc.minio_key,
        statut=doc.statut.value
    )
    return {"document_id": doc_id}


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
    driver.delete_entity("Document", document_id)
    return {"status": "deleted"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Erreur inattendue {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )
