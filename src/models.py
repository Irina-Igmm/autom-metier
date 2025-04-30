from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Status(Enum):
    ACTIF = "actif"
    ARCHIVE = "archivé"


class Priority(Enum):
    BASSE = "basse"
    MOYENNE = "moyenne"
    HAUTE = "haute"


class Document(BaseModel):
    id: Optional[str] = None
    titre: str
    type: str
    minio_key: str
    date_creation: datetime = Field(default_factory=datetime.utcnow)
    statut: Status = Status.ACTIF


class DataType(Enum):
    STRING = "string"
    FLOAT = "float"
    DATE = "date"


class Variable(BaseModel):
    id: Optional[str]
    key: str
    data_type: DataType
    value: Optional[str]
    date_extraction: datetime = Field(default_factory=datetime.utcnow)
    confiance: Optional[float]


class StepCondition(BaseModel):
    """Condition for executing a step based on variable value"""
    variable_key: str
    operator: str  # equals, not_equals, contains, greater_than, less_than
    value: Any
    
    def evaluate(self, variables: Dict[str, Any]) -> bool:
        """Evaluate if the condition is true based on the provided variables"""
        if self.variable_key not in variables:
            return False
            
        var_value = variables[self.variable_key]
        
        if self.operator == "equals":
            return var_value == self.value
        elif self.operator == "not_equals":
            return var_value != self.value
        elif self.operator == "contains":
            return self.value in str(var_value)
        elif self.operator == "greater_than":
            return float(var_value) > float(self.value)
        elif self.operator == "less_than":
            return float(var_value) < float(self.value)
        return False


class Step(BaseModel):
    outil: str
    params: Dict[str, str]
    ordre: int
    dependencies: List[str] = []  # IDs of steps this step depends on
    condition: Optional[StepCondition] = None  # Condition to execute this step
    retry_strategy: Optional[Dict[str, Any]] = None  # Retry settings if step fails
    timeout_seconds: int = 60  # Maximum time allowed for step execution
    on_failure: str = "abort"  # abort, continue, or retry
    
    def should_execute(self, variables: Dict[str, Any]) -> bool:
        """Check if step should execute based on its condition"""
        if not self.condition:
            return True
        return self.condition.evaluate(variables)


class Scenario(BaseModel):
    id: Optional[str]
    nom: str
    description: Optional[str] = ""
    priorite: Priority = Priority.MOYENNE
    documents: List[str] = []
    variables: List[str] = []
    etapes: List[Step] = []


class RunStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class Automatisation(BaseModel):
    id: Optional[str]
    scenario_id: str
    agent_config: Dict[str, Any]
    date_execution: Optional[datetime] = None
    statut: RunStatus = RunStatus.QUEUED
    resultat: Optional[Dict]
    duree_ms: Optional[int]
