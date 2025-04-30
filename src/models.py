from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
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
    key: str
    data_type: DataType
    value: Optional[str]
    date_extraction: datetime = Field(default_factory=datetime.utcnow)
    confiance: Optional[float]


class Step(BaseModel):
    outil: str
    params: Dict[str, str]
    ordre: int


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
    agent_config: Dict[str, str]
    date_execution: Optional[datetime] = None
    statut: RunStatus = RunStatus.QUEUED
    resultat: Optional[Dict]
    duree_ms: Optional[int]
