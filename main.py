from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from src.neo4j_driver import Neo4jDriver

app = FastAPI()

class VariableCreate(BaseModel):
    nom: str
    type: str

class ScenarioCreate(BaseModel):
    nom: str
    description: str
    priorite: str
    document_ids: Optional[List[str]] = Field(default_factory=list)
    variables: Optional[List[VariableCreate]] = Field(default_factory=list)

def get_driver():
    try:
        return Neo4jDriver()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j non disponible : {str(e)}")

@app.get("/")
def read_root():
    return {"message": "API is running"}

@app.post("/scenarios/")
def create_scenario(scenario: ScenarioCreate, driver: Neo4jDriver = Depends(get_driver)):
    try:
        scenario_id = driver.create_scenario(
            nom=scenario.nom,
            description=scenario.description,
            priorite=scenario.priorite,
            document_ids=scenario.document_ids,
            variables=[var.dict() for var in scenario.variables]
        )
        return {"scenario_id": scenario_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))