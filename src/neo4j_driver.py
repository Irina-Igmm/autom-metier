# src/neo4j_driver.py
"""
Module pour la gestion des connexions et requêtes Neo4j.
Fournit une interface robuste et fiable pour interagir avec la base de données graphe.
"""
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Driver, Transaction, exceptions as neo4j_exceptions
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from .config import config

logger = logging.getLogger(__name__)


class IDriver(ABC):
    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def create_scenario(self, *args, **kwargs) -> str:
        pass

    @abstractmethod
    def link_variable_to_document(
        self, document_id: str, variable_nom: str, variable_valeur: Any,
        variable_type: str, methode: str, confiance: float
    ) -> str:
        pass

    @abstractmethod
    def start_automation(self, scenario_id: str, agent_config: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    def update_automation_status(
        self, automation_id: str, statut: str,
        resultat: Optional[str], duree_ms: Optional[int]
    ) -> None:
        pass

    @abstractmethod
    def get_scenario_with_relations(self, scenario_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_document(self, document_id: str) -> Dict[str, Any]:
        pass


class Neo4jDriver(IDriver):
    """Gestionnaire de connexion et requêtes Neo4j avec retry,
       context manager et timeout configurables."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.uri = uri or config.NEO4J_URI
        self.user = user or config.NEO4J_USER
        self.password = password or config.NEO4J_PASSWORD
        self.max_retry = config.NEO4J_MAX_RETRY
        self.retry_delay = config.NEO4J_RETRY_DELAY
        self.connection_timeout = config.NEO4J_CONN_TIMEOUT
        self.driver: Optional[Driver] = None
        self.connect()
        try:
            self._create_constraints()
        except Exception:
            logger.exception("Échec de la création des contraintes Neo4j")

    def __enter__(self) -> "Neo4jDriver":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(neo4j_exceptions.ServiceUnavailable),
        reraise=True
    )
    def connect(self) -> None:
        """Établit une connexion à Neo4j avec retry."""
        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            max_connection_lifetime=self.connection_timeout,
            connection_timeout=self.connection_timeout,
            encrypted=True,
        )
        # health check
        with self.driver.session() as session:
            session.run("RETURN 1 AS ok").single()
            logger.info("Connexion établie à Neo4j")

    def close(self) -> None:
        if self.driver:
            self.driver.close()
            self.driver = None
            logger.info("Connexion Neo4j fermée")

    def _create_constraints(self) -> None:
        constraints = [
            ("Document", "id"),
            ("Variable", "id"),
            ("Scenario", "id"),
            ("Automatisation", "id"),
        ]
        with self.driver.session() as session:
            for label, prop in constraints:
                session.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )
        logger.info("Contraintes Neo4j créées")

    def _run_tx(self, cypher: str, params: Dict[str, Any] = None) -> Any:
        params = params or {}
        try:
            with self.driver.session() as session:
                return session.run(cypher, **params)
        except Exception:
            logger.exception("Erreur lors de l'exécution de la requête Cypher")
            raise

    def create_scenario(
        self,
        nom: str,
        description: str,
        priorite: str,
        document_ids: Optional[List[str]] = None,
        variables: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        doc_ids = document_ids or []
        vars_ = variables or []
        scenario_id = str(uuid.uuid4())
        cypher = (
            "CREATE (s:Scenario {id: $id, nom: $nom, description: $desc, "
            "dateCreation: datetime(), statut: 'actif', priorite: $prio}) RETURN s.id AS id"
        )
        record = self._run_tx(cypher, {
            "id": scenario_id,
            "nom": nom,
            "desc": description,
            "prio": priorite,
        }).single()
        for d in doc_ids:
            self.link_scenario_to_document(scenario_id, d)
        for var in vars_:
            self.link_variable_to_scenario(
                scenario_id, var["key"], var["data_type"])
        return record["id"]

    def link_scenario_to_document(
        self, scenario_id: str, document_id: str, role: str = "input"
    ) -> None:
        cypher = (
            "MATCH (s:Scenario {id: $sid}), (d:Document {id: $did}) "
            "MERGE (s)-[:USES_DOCUMENT {role: $role}]->(d)"
        )
        self._run_tx(cypher, {"sid": scenario_id,
                     "did": document_id, "role": role})

    def link_variable_to_scenario(
        self, scenario_id: str, key: str, data_type: str, role: str = "extract"
    ) -> None:
        var_id = str(uuid.uuid4())
        cypher = (
            "MATCH (s:Scenario {id: $sid}) "
            "CREATE (v:Variable {"
            "id: $vid, key: $key, data_type: $dt, dateExtraction: datetime(), confiance: null})"
            "-[:USES_VARIABLE {role: $role}]->(s)"
        )
        self._run_tx(cypher, {"sid": scenario_id, "vid": var_id,
                     "key": key, "dt": data_type, "role": role})

    def link_variable_to_document(
        self, document_id: str, variable_nom: str, variable_valeur: Any,
        variable_type: str = "string", methode: str = "IA", confiance: float = 1.0
    ) -> str:
        var_id = str(uuid.uuid4())
        cypher = (
            "MATCH (d:Document {id: $document_id}) "
            "CREATE (v:Variable {"
            "id: $vid, key: $key, data_type: $dt, value: $value, "
            "dateExtraction: datetime(), confiance: $conf})"
            "CREATE (d)-[:HAS_VARIABLE {method: $method, confidence: $conf}]->(v)"
            " RETURN v.id AS id"
        )
        record = self._run_tx(cypher, {
            "document_id": document_id,
            "vid": var_id,
            "key": variable_nom,
            "dt": variable_type,
            "value": variable_valeur,
            "method": methode,
            "conf": confiance,
        }).single()
        return record["id"]

    def start_automation(self, scenario_id: str, agent_config: Dict[str, Any]) -> str:
        automation_id = str(uuid.uuid4())
        cypher = (
            "MATCH (s:Scenario {id: $sid}) "
            "CREATE (a:Automatisation {"
            "id: $aid, dateExecution: datetime(), statut: 'queued', resultat: null, duree: 0, agent_config: $cfg})"
            "CREATE (a)-[:TRIGGERS]->(s) RETURN a.id AS id"
        )
        record = self._run_tx(
            cypher, {"sid": scenario_id, "aid": automation_id, "cfg": agent_config}).single()
        return record["id"]

    def update_automation_status(
        self, automation_id: str, statut: str,
        resultat: Optional[str] = None, duree_ms: Optional[int] = None
    ) -> None:
        statut_map = {"en cours": "running",
                      "terminé": "success", "échoué": "error"}
        mapped = statut_map.get(statut, statut)
        cypher = "MATCH (a:Automatisation {id: $id}) SET a.statut = $stat"
        params: Dict[str, Any] = {"id": automation_id, "stat": mapped}
        if resultat is not None:
            cypher += ", a.resultat = $res"
            params["res"] = resultat
        if duree_ms is not None:
            cypher += ", a.duree = $dur"
            params["dur"] = duree_ms
        self._run_tx(cypher, params)

    def get_scenario_with_relations(self, scenario_id: str) -> Dict[str, Any]:
        cypher = (
            "MATCH (s:Scenario {id: $id})"
            " OPTIONAL MATCH (s)-[r:USES_DOCUMENT]->(d:Document)"
            " OPTIONAL MATCH (s)-[r2:USES_VARIABLE]->(v:Variable)"
            " RETURN s AS scenario, collect(distinct d) AS documents, collect(distinct v) AS variables"
        )
        record = self._run_tx(cypher, {"id": scenario_id}).single()
        if not record:
            return {}
        return {
            "scenario": dict(record["scenario"]),
            "documents": [dict(d) for d in record["documents"]],
            "variables": [dict(v) for v in record["variables"]]
        }

    def get_document(self, document_id: str) -> Dict[str, Any]:
        cypher = "MATCH (d:Document {id: $id}) RETURN d"
        record = self._run_tx(cypher, {"id": document_id}).single()
        if not record:
            return {}
        return dict(record["d"])

    def check_duplicate_invoice(
        self, num_facture: str, fournisseur: str, document_id: Optional[str] = None
    ) -> bool:
        cypher = (
            "MATCH (d:Document {type: 'facture'})"
            " WHERE EXISTS((d)-[:HAS_VARIABLE]->(:Variable {key: 'numeroFacture', value: $num}))"
            "   AND EXISTS((d)-[:HAS_VARIABLE]->(:Variable {key: 'fournisseur', value: $fou}))"
        )
        params: Dict[str, Any] = {"num": num_facture, "fou": fournisseur}
        if document_id:
            cypher += " AND d.id <> $did"
            params["did"] = document_id
        cypher += " RETURN count(d) > 0 AS dup"
        result = self._run_tx(cypher, params).single()
        return bool(result["dup"])

    def delete_entity(self, label: str, entity_id: str) -> None:
        cypher = (
            f"MATCH (n:{label} {{id: $id}}) DETACH DELETE n"
        )
        self._run_tx(cypher, {"id": entity_id})

    def find_entities(
        self, label: str, filters: Dict[str, Any], limit: int = 100
    ) -> List[Dict[str, Any]]:
        where_clauses = " AND ".join([f"n.{k} = ${k}" for k in filters])
        cypher = f"MATCH (n:{label}) WHERE {where_clauses} RETURN n LIMIT $limit"
        params = {**filters, "limit": limit}
        results = self._run_tx(cypher, params)
        return [dict(rec["n"]) for rec in results]

    def health_check(self) -> bool:
        try:
            self._run_tx("RETURN 1").single()
            return True
        except Exception:
            return False

    def begin_transaction(self) -> Transaction:
        session = self.driver.session()
        return session.begin_transaction()

    def commit(self, tx: Transaction) -> None:
        tx.commit()
        tx.close()

    def rollback(self, tx: Transaction) -> None:
        tx.rollback()
        tx.close()


# Instance partagée pour l'application
# neo4j_driver = Neo4jDriver()
