# main.py
import os
from datetime import datetime, timedelta
import time
import json
import uuid
import asyncio
from collections import deque
import threading
from contextlib import asynccontextmanager
from typing import Dict, List, Any, Optional, Generator, Callable

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from pydantic import BaseModel

from src.agent import run_agent_tool
from src.models import Scenario, Automatisation, Document as DocumentModel
from src.neo4j_driver import Neo4jDriver
from scripts.minio_manager import MinioManager
from src.task_queue import TaskQueue
import logging

from src.config import config

# Initialize TaskQueue instance
task_queue = TaskQueue(max_concurrent=config.MAX_CONCURRENT_TASKS if hasattr(config, 'MAX_CONCURRENT_TASKS') else 3)

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
    tasks = task_queue.get_all_tasks()

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
    task_info = task_queue.get_task_info(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_info


@app.post("/api/scenarios/{scenario_id}/run", dependencies=[Depends(verify_token)])
async def run_scenario_enhanced(
    scenario_id: str,
    driver: Neo4jDriver = Depends(get_driver),
    minio_manager: MinioManager = Depends(get_minio_manager),
    wait_for_result: bool = False,
):
    """Run a scenario with enhanced task queue management and status tracking"""
    # Create automation in Neo4j
    automation_id = driver.start_automation(scenario_id, agent_config={})

    # Define the execution function
    def execute_scenario(scenario_id=scenario_id, automation_id=automation_id):
        # Get the task_id from the TaskQueue context
        task_id = threading.current_thread().task_id if hasattr(
            threading.current_thread(), 'task_id') else None
        task_info = task_queue.tasks.get(task_id) if task_id else None

        start_time = time.time()
        variables = {}  # Store extracted variables for conditional execution

        try:
            # Log the start of execution
            if task_info:
                task_info.log(f"Starting scenario execution: {scenario_id}")

            # Get scenario details with related documents and variables
            data = driver.get_scenario_with_relations(scenario_id)
            if not data:
                raise ValueError(f"Scenario not found: {scenario_id}")

            if task_info:
                task_info.log(
                    f"Scenario loaded: {data['scenario'].get('nom', 'Unnamed')}")
                task_info.update_progress(10)

            # Get steps and dependencies
            steps = data['scenario'].get('etapes', [])
            if not steps:
                if task_info:
                    task_info.log("No steps found in scenario")
                raise ValueError("Scenario has no steps to execute")

            # Sort steps by order
            steps = sorted(steps, key=lambda e: e['ordre'])
            total_steps = len(steps)

            # Initialize results and executed steps tracker
            results = []
            executed_steps = set()
            step_outputs = {}

            # Track progress
            if task_info:
                task_info.log(f"Executing {total_steps} steps")
                task_info.update_progress(20)

            # First, execute steps that extract variables
            for i, step in enumerate(steps):
                # Skip steps with dependencies for now
                if step.get('dependencies'):
                    continue

                # Execute extraction steps first
                if step.get('outil') == 'extract_variables':
                    tool = step['outil']
                    params = step.get('params', {})

                    if task_info:
                        task_info.log(
                            f"Executing variable extraction step: {tool}")

                    try:
                        output = run_agent_tool(tool, **params)

                        # Store variables for conditional execution
                        if isinstance(output, dict):
                            variables.update(output)

                        step_outputs[i] = output
                        executed_steps.add(i)

                        results.append({
                            'step': i + 1,
                            'outil': tool,
                            'status': 'success',
                            'result': output
                        })

                        # Update progress
                        progress_pct = 20 + \
                            (30 * len(executed_steps) / total_steps)
                        if task_info:
                            task_info.log(
                                f"Extracted variables: {', '.join(output.keys()) if isinstance(output, dict) else 'none'}")
                            task_info.update_progress(int(progress_pct))

                    except Exception as e:
                        if task_info:
                            task_info.log(
                                f"Error in extraction step: {str(e)}", "ERROR")

                        results.append({
                            'step': i + 1,
                            'outil': tool,
                            'status': 'error',
                            'error': str(e)
                        })

            # Then execute the remaining steps with dependency and condition checking
            remaining_steps = [i for i in range(
                len(steps)) if i not in executed_steps]

            while remaining_steps:
                progress = False

                for i in list(remaining_steps):
                    step = steps[i]
                    tool = step['outil']
                    params = step.get('params', {})
                    dependencies = step.get('dependencies', [])
                    condition = step.get('condition')

                    # Check if dependencies are met
                    deps_met = all(
                        dep in executed_steps for dep in dependencies)
                    if not deps_met:
                        continue

                    # Check if condition is met
                    condition_met = True
                    if condition:
                        var_key = condition.get('variable_key')
                        operator = condition.get('operator')
                        value = condition.get('value')

                        if var_key and var_key in variables:
                            var_value = variables[var_key]

                            if operator == 'equals' and var_value != value:
                                condition_met = False
                            elif operator == 'not_equals' and var_value == value:
                                condition_met = False
                            elif operator == 'contains' and value not in str(var_value):
                                condition_met = False
                            elif operator == 'greater_than' and not (float(var_value) > float(value)):
                                condition_met = False
                            elif operator == 'less_than' and not (float(var_value) < float(value)):
                                condition_met = False

                    if not condition_met:
                        if task_info:
                            task_info.log(
                                f"Skipping step {i+1} ({tool}) - condition not met")

                        # Mark as executed but skipped
                        executed_steps.add(i)
                        remaining_steps.remove(i)
                        results.append({
                            'step': i + 1,
                            'outil': tool,
                            'status': 'skipped',
                            'reason': 'condition not met'
                        })
                        progress = True
                        continue

                    # Execute the step
                    if task_info:
                        task_info.log(
                            f"Executing step {i+1}/{total_steps}: {tool}")

                    try:
                        # Execute with retry if configured
                        retry_strategy = step.get('retry_strategy')
                        timeout = step.get('timeout_seconds', 60)

                        # Basic timeout handling
                        def execute_with_timeout():
                            return run_agent_tool(tool, **params)

                        if retry_strategy:
                            max_attempts = retry_strategy.get(
                                'max_attempts', 3)
                            delay = retry_strategy.get('delay_seconds', 2)

                            # Simple retry logic
                            attempt = 0
                            last_error = None

                            while attempt < max_attempts:
                                try:
                                    output = execute_with_timeout()
                                    break
                                except Exception as e:
                                    attempt += 1
                                    last_error = e
                                    if attempt < max_attempts:
                                        if task_info:
                                            task_info.log(
                                                f"Retry {attempt}/{max_attempts} after error: {str(e)}")
                                        time.sleep(delay)

                            if attempt == max_attempts:
                                raise last_error
                        else:
                            # No retry, just execute once
                            output = execute_with_timeout()

                        # Store output for dependencies
                        step_outputs[i] = output

                        # Store variables if this is a variable extraction step
                        if tool == 'extract_variables' and isinstance(output, dict):
                            variables.update(output)

                        results.append({
                            'step': i + 1,
                            'outil': tool,
                            'status': 'success',
                            'result': output
                        })

                    except Exception as e:
                        if task_info:
                            task_info.log(
                                f"Error in step {i+1}: {str(e)}", "ERROR")

                        results.append({
                            'step': i + 1,
                            'outil': tool,
                            'status': 'error',
                            'error': str(e)
                        })

                        # Handle failure based on the step's configuration
                        on_failure = step.get('on_failure', 'abort')
                        if on_failure == 'abort':
                            if task_info:
                                task_info.log(
                                    "Aborting scenario due to step failure")
                            raise ValueError(
                                f"Step {i+1} failed and is configured to abort: {str(e)}")

                    # Mark as executed
                    executed_steps.add(i)
                    remaining_steps.remove(i)
                    progress = True

                    # Update progress
                    progress_pct = 50 + \
                        (40 * len(executed_steps) / total_steps)
                    if task_info:
                        task_info.update_progress(int(progress_pct))

                # If no progress was made in this iteration, we have a dependency cycle
                if not progress and remaining_steps:
                    if task_info:
                        task_info.log(
                            "Dependency cycle or unmet dependencies detected", "ERROR")
                    raise ValueError(
                        "Cannot complete scenario - dependency cycle or unmet dependencies")

            # Calculate duration and update automation status
            duration_ms = int((time.time() - start_time) * 1000)

            if task_info:
                task_info.log(
                    f"Scenario executed successfully in {duration_ms}ms")
                task_info.update_progress(100)

            # Update Neo4j with results
            driver.update_automation_status(
                automation_id=automation_id,
                statut='terminé',
                resultat=json.dumps(results),
                duree_ms=duration_ms
            )

            return {
                'automation_id': automation_id,
                'scenario_id': scenario_id,
                'status': 'completed',
                'duration_ms': duration_ms,
                'steps': results
            }

        except Exception as e:
            # Log the error and update the automation status
            error_msg = str(e)
            if task_info:
                task_info.log(
                    f"Scenario execution failed: {error_msg}", "ERROR")

            duration_ms = int((time.time() - start_time) * 1000)

            try:
                driver.update_automation_status(
                    automation_id=automation_id,
                    statut='échoué',
                    resultat=json.dumps({'error': error_msg}),
                    duree_ms=duration_ms
                )
            except Exception as update_error:
                if task_info:
                    task_info.log(
                        f"Failed to update automation status: {str(update_error)}", "ERROR")

            return {
                'automation_id': automation_id,
                'scenario_id': scenario_id,
                'status': 'failed',
                'error': error_msg,
                'duration_ms': duration_ms
            }

    # Add task to the queue
    task_id = task_queue.add_task(
        task_type="scenario_execution",
        task_func=execute_scenario,
        params={"scenario_id": scenario_id, "automation_id": automation_id}
    )

    # Wait for result if requested
    if wait_for_result:
        # Poll for task completion
        max_wait_sec = 60  # Maximum wait time (adjust as needed)
        poll_interval_sec = 0.5
        waited_sec = 0

        while waited_sec < max_wait_sec:
            task_info = task_queue.get_task_info(task_id)
            if task_info["status"] in ["completed", "failed"]:
                return {
                    "task_id": task_id,
                    "automation_id": automation_id,
                    "status": task_info["status"],
                    "result": task_info["result"],
                    "error": task_info.get("error")
                }

            await asyncio.sleep(poll_interval_sec)
            waited_sec += poll_interval_sec

        # If we get here, we've timed out waiting
        return {
            "task_id": task_id,
            "automation_id": automation_id,
            "status": "running",
            "message": "Task is still running, check status later"
        }

    # Return immediately with task ID
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
        session.run("MATCH (v:Variable {id: $id}) DETACH DELETE v", id=variable_id)
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
        record = session.run(
            "MATCH (a:Automatisation {id: $id}) RETURN a", id=automatisation_id
        ).single()
    if not record:
        raise HTTPException(status_code=404, detail="Automatisation non trouvée")
    return dict(record["a"])


@app.delete("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
def delete_automatisation(automatisation_id: str, driver: Neo4jDriver = Depends(get_driver)):
    with driver.driver.session() as session:
        session.run("MATCH (a:Automatisation {id: $id}) DETACH DELETE a", id=automatisation_id)
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
