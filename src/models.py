from datetime import datetime  
from pydantic import BaseModel, Field
from typing import List, Optional

class Document(BaseModel):
    id: Optional[str] = None
    nom: str
    type: str
    minio_key: str
    date_creation: Optional[datetime] = None
    statut: Optional[str] = "actif"

class Variable(BaseModel):
    id: Optional[str] = None
    nom: str
    type: str
    valeur: Optional[str] = None
    date_extraction: Optional[datetime] = None
    confiance: Optional[float] = None

class Scenario(BaseModel):
    id: Optional[str] = None
    nom: str
    description: Optional[str] = ""
    priorite: Optional[str] = "moyenne"
    documents: List[str] = Field(default_factory=list)
    variables: List[str] = Field(default_factory=list)

class Automatisation(BaseModel):
    id: Optional[str] = None
    scenario_id: str
    date_execution: Optional[datetime] = None
    statut: Optional[str] = "en cours"
    resultat: Optional[str] = None
    duree: Optional[int] = 0