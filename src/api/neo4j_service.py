"""
Service Neo4j - Endpoints pour la gestion des entités Neo4j (documents, variables, automatisations, résultats)
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Dict, Any, List, Optional

from src.models import Document as DocumentModel, Variable, Automatisation, ResultatGenere, VariableCreate
from src.neo4j_driver import Neo4jDriver

# Import des dépendances d'authentification depuis auth.py
from src.auth import verify_token, get_driver

# Création du router
router = APIRouter()

# --- Documents endpoints ---
@router.post("/documents/", dependencies=[Depends(verify_token)])
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


@router.get("/documents/{document_id}", dependencies=[Depends(verify_token)])
def get_document(document_id: str, driver: Neo4jDriver = Depends(get_driver)):
    """Récupérer un document par ID"""
    doc = driver.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    return doc


@router.delete("/documents/{document_id}", dependencies=[Depends(verify_token)])
def delete_document(document_id: str, driver: Neo4jDriver = Depends(get_driver)):
    """Supprimer un document et ses relations"""
    driver.delete_entity("Document", document_id)
    return {"status": "deleted"}

# --- Variables endpoints ---
@router.post("/variables/", dependencies=[Depends(verify_token)])
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


@router.get("/variables/{variable_id}", dependencies=[Depends(verify_token)])
def get_variable(variable_id: str, driver: Neo4jDriver = Depends(get_driver)):
    query = "MATCH (v:Variable {id: $id}) RETURN v"
    with driver.driver.session() as session:
        record = session.run(query, id=variable_id).single()
        if not record:
            raise HTTPException(
                status_code=404, detail="Variable non trouvée")
        return dict(record["v"])


@router.delete("/variables/{variable_id}", dependencies=[Depends(verify_token)])
def delete_variable(variable_id: str, driver: Neo4jDriver = Depends(get_driver)):
    with driver.driver.session() as session:
        session.run(
            "MATCH (v:Variable {id: $id}) DETACH DELETE v", id=variable_id)
    return {"status": "deleted"}

# --- Automatisations endpoints ---
@router.post("/automatisations/", dependencies=[Depends(verify_token)])
def create_automatisation(
    automatisation: Automatisation,
    driver: Neo4jDriver = Depends(get_driver),
):
    automatisation_id = driver.start_automation(
        scenario_id=automatisation.scenario_id,
        agent_config=automatisation.agent_config
    )
    return {"automatisation_id": automatisation_id}


@router.get("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
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


@router.delete("/automatisations/{automatisation_id}", dependencies=[Depends(verify_token)])
def delete_automatisation(automatisation_id: str, driver: Neo4jDriver = Depends(get_driver)):
    with driver.driver.session() as session:
        session.run(
            "MATCH (a:Automatisation {id: $id}) DETACH DELETE a", id=automatisation_id)
    return {"status": "deleted"}

# --- Résultats endpoints ---
@router.post("/resultats/", dependencies=[Depends(verify_token)])
def create_resultat(
    resultat: ResultatGenere,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Créer un résultat généré dans Neo4j"""
    resultat_id = driver.create_resultat_genere(
        titre=resultat.titre,
        minio_key=resultat.minio_key,
        automatisation_id=resultat.automatisation_id,
        scenario_id=resultat.scenario_id,
        type_resultat=resultat.type,
        variables_utilisees=resultat.variables_utilisees,
        metadonnees=resultat.metadonnees
    )
    return {"resultat_id": resultat_id}


@router.get("/resultats/automatisation/{automatisation_id}", dependencies=[Depends(verify_token)])
def get_resultats_automatisation(
    automatisation_id: str,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Récupérer tous les résultats générés associés à une automatisation"""
    resultats = driver.get_resultats_pour_automatisation(automatisation_id)
    return resultats


@router.get("/resultats/scenario/{scenario_id}", dependencies=[Depends(verify_token)])
def get_resultats_scenario(
    scenario_id: str,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Récupérer tous les résultats générés associés à un scénario"""
    resultats = driver.get_resultats_pour_scenario(scenario_id)
    return resultats

# --- Scenarios endpoints (sauf ceux à laisser dans main.py) ---
@router.delete("/scenarios/{scenario_id}", dependencies=[Depends(verify_token)])
def delete_scenario(
    scenario_id: str,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Delete a scenario and its relationships"""
    try:
        # First check if the scenario exists
        scenario = driver.get_scenario_with_relations(scenario_id)
        if not scenario:
            raise HTTPException(status_code=404, detail=f"Scenario with ID {scenario_id} not found")
        
        # Delete the scenario with its relationships
        driver.delete_entity("Scenario", scenario_id)
        return {"status": "deleted", "scenario_id": scenario_id}
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error deleting scenario: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting scenario: {str(e)}")

@router.get("/scenarios/{scenario_id}", dependencies=[Depends(verify_token)])
def get_scenario(
    scenario_id: str,
    driver: Neo4jDriver = Depends(get_driver)
):
    """Get a scenario by ID with its relationships"""
    scenario = driver.get_scenario_with_relations(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario with ID {scenario_id} not found")
    return scenario