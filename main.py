# main.py
import os
import uuid
import json
from datetime import datetime
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.models import Scenario
from src.neo4j_driver import Neo4jDriver
from src.auth import verify_token, get_driver, generate_token
from src.api import neo4j_service, minio_service

# Initialize app with context manager to setup static directory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create static directory if it doesn't exist
    os.makedirs("static", exist_ok=True)
    yield

# Initialize FastAPI app
app = FastAPI(lifespan=lifespan, title="Automatisation de scénarios métier")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(neo4j_service.router, tags=["Neo4j"])
app.include_router(minio_service.router, tags=["MinIO"])


@app.post("/generate-token/")
def token_endpoint():
    """Génère un JWT valide pour 1 heure"""
    return generate_token()

# Conserver uniquement les endpoints /scenarios/ et /scenarios/{id}/run


@app.post("/scenarios/", dependencies=[Depends(verify_token)])
def create_scenario(
    scenario: Scenario,
    driver: Neo4jDriver = Depends(get_driver),
):
    """
    Créer un nouveau scénario métier

    Crée un nouveau scénario avec les étapes, documents et variables associées
    """
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


@app.post("/api/scenarios/{scenario_id}/run", dependencies=[Depends(verify_token)])
async def run_scenario_enhanced(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    driver: Neo4jDriver = Depends(get_driver),
):
    """Exécuter un scénario par son ID de manière asynchrone"""
    # Create automation instance in Neo4j
    automation_id = driver.start_automation(
        scenario_id, agent_config=json.dumps({}))
    task_id = str(uuid.uuid4())

    # Initialize task status storage if needed
    if not hasattr(run_scenario_enhanced, "tasks"):
        run_scenario_enhanced.tasks = {}

    # Initialize task status
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

    # Register task for tracking
    run_scenario_enhanced.tasks[task_id] = task_status

    def update_task(**kwargs):
        run_scenario_enhanced.tasks[task_id].update(**kwargs)

    def log(msg, level="INFO"):
        run_scenario_enhanced.tasks[task_id]["logs"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": msg
        })

    def execute_scenario():
        try:
            # Update task status
            update_task(status="running",
                        started_at=datetime.utcnow().isoformat())
            log("Starting scenario execution")

            # Get scenario details from Neo4j
            scenario_details = driver.get_scenario_with_relations(scenario_id)
            if not scenario_details:
                raise Exception(f"Scenario {scenario_id} not found")

            # Run the AI agent
            from src.agent import run_agent_tool
            result = run_agent_tool(
                scenario_id=scenario_id,
                automation_id=automation_id
            )

            if "error" in result:
                raise Exception(result["error"])

            # Update automation status in Neo4j
            driver.update_automation_status(
                automation_id=automation_id,
                statut="terminé",
                resultat=json.dumps(result),
                duree_ms=int((datetime.utcnow() -
                              datetime.fromisoformat(run_scenario_enhanced.tasks[task_id]["started_at"]))
                             .total_seconds() * 1000)
            )

            # Update task status
            update_task(
                status="completed",
                completed_at=datetime.utcnow().isoformat(),
                progress=100,
                result=result
            )
            log("Scenario execution completed successfully")

        except Exception as e:
            error_msg = str(e)
            log(f"Error executing scenario: {error_msg}", level="ERROR")
            # Update automation status in Neo4j
            driver.update_automation_status(
                automation_id=automation_id,
                statut="échoué",
                resultat=error_msg
            )
            # Update task status
            update_task(
                status="failed",
                completed_at=datetime.utcnow().isoformat(),
                error=error_msg
            )

    # Schedule background execution
    background_tasks.add_task(execute_scenario)
    return {
        "task_id": task_id,
        "automation_id": automation_id,
        "status": "queued",
        "message": "Task queued for execution"
    }


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Récupérer le statut d'une tâche d'exécution de scénario"""
    tasks = getattr(run_scenario_enhanced, "tasks", {})
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Erreur inattendue: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )
