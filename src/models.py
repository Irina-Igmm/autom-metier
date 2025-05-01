from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Union
import uuid
from pydantic import BaseModel, Field


class Status(Enum):
    ACTIF = "actif"
    ARCHIVE = "archive"
    BROUILLON = "brouillon"


class Priority(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Document(BaseModel):
    id: Optional[str] = str(uuid.uuid4())
    titre: str
    type: str
    minio_key: str
    statut: Status = Status.ACTIF
    date_creation: datetime = Field(default_factory=datetime.utcnow)


class VariableType(str, Enum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"


class DataType(Enum):
    STRING = "string"
    FLOAT = "float"
    DATE = "date"


class Variable(BaseModel):
    id: Optional[str] = str(uuid.uuid4())
    key: str
    value: Optional[Any] = None
    data_type: VariableType = VariableType.TEXT
    date_extraction: datetime = Field(default_factory=datetime.utcnow)
    confiance: Optional[float]
    
    
class VariableCreate(BaseModel):
    """Modèle pour la création d'une variable associée à un document"""
    document_id: str
    key: str
    value: Any
    data_type: str = VariableType.TEXT.value
    methode: str = "IA"
    confiance: float = 1.0


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
    # Retry settings if step fails
    retry_strategy: Optional[Dict[str, Any]] = None
    timeout_seconds: int = 60  # Maximum time allowed for step execution
    on_failure: str = "abort"  # abort, continue, or retry

    def should_execute(self, variables: Dict[str, Any]) -> bool:
        """Check if step should execute based on its condition"""
        if not self.condition:
            return True
        return self.condition.evaluate(variables)


class Etape(BaseModel):
    nom: str
    description: str
    ordre: int


class Scenario(BaseModel):
    id: Optional[str] = str(uuid.uuid4())
    nom: str
    description: Optional[str] = ""
    priorite: Priority = Priority.MEDIUM
    documents: List[str] = []
    variables: List[Variable] = [] 
    etapes: List[Etape] = []


class RunStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class Automatisation(BaseModel):
    id: Optional[str] = str(uuid.uuid4())
    scenario_id: str
    agent_config: Dict[str, Any]
    date_execution: Optional[datetime] = None
    statut: RunStatus = RunStatus.QUEUED
    resultat: Optional[Dict]
    duree_ms: Optional[int]


# Nouveau modèle pour les résultats générés
class ResultatGenere(BaseModel):
    """Modèle pour représenter un résultat généré par une automatisation"""
    id: Optional[str] = None
    automatisation_id: str
    scenario_id: str
    type: str = "document"  # document, email, pdf, etc.
    titre: str
    minio_key: Optional[str] = None  # Référence au fichier dans MinIO
    variables_utilisees: List[str] = []  # Liste des IDs de variables utilisées
    date_creation: Optional[datetime] = Field(default_factory=datetime.utcnow)
    metadonnees: Optional[Dict[str, Any]] = Field(default_factory=dict)
