# src/neo4j_driver.py
"""
Module pour la gestion des connexions et requêtes Neo4j.
Fournit une interface robuste et fiable pour interagir avec la base de données graphe.
"""
import json
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
    def create_and_link_variable_to_document(
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
            encrypted=False,  # Désactive le chiffrement pour connexions locales
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

    def _run_tx(self, cypher: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Exécute la requête et retourne la liste complète des enregistrements
        (chaque record.data()) avant de fermer la session.
        """
        # Ensure driver is connected
        if self.driver is None:
            self.connect()

        params = params or {}
        try:
            with self.driver.session() as session:
                result = session.run(cypher, **params)
                # Bufferisation complète
                records = [record.data() for record in result]
                return records
        except Exception:
            logger.exception("Erreur lors de l'exécution de la requête Cypher")
            raise

    def create_document(self, document=None, **kwargs) -> str:
        """
        Crée un nœud Document à partir d'un modèle Pydantic Document ou de paramètres.
        """
        from src.models import Document as DocumentModel, Status
        # Si on reçoit une instance de DocumentModel
        if isinstance(document, DocumentModel):
            doc_model = document
        else:
            # Récupération des champs legacy
            titre = kwargs.get('titre') or kwargs.get('nom')
            type_ = kwargs.get('type') or kwargs.get('type_doc')
            minio_key = kwargs.get('minio_key') or kwargs.get('chemin')
            statut = kwargs.get('statut', Status.ACTIF.value)
            # Création d'une instance DocumentModel pour validation
            doc_model = DocumentModel(
                titre=titre,
                type=type_,
                minio_key=minio_key,
                statut=Status(statut)
            )
        # Génération d'un UUID
        doc_id = str(uuid.uuid4())
        cypher = (
            "CREATE (d:Document {id: $id, titre: $titre, type: $type, "
            "minio_key: $key, dateCreation: datetime(), statut: $statut}) "
            "RETURN d.id AS id"
        )
        # _run_tx retourne désormais List[Dict[str,Any]]
        records = self._run_tx(cypher, {
            "id": doc_id,
            "titre": doc_model.titre,
            "type": doc_model.type,
            "key": doc_model.minio_key,
            "statut": doc_model.statut.value,
        })
        if not records:
            raise RuntimeError("Échec de la création du document")
        # Premier enregistrement -> id
        return records[0]["id"]

    def create_node(self, label: str, props: Dict[str, Any]) -> str:
        """Crée un nœud avec un label arbitraire et des propriétés données."""
        # Assure un id dans props
        node_id = props.get('id', str(uuid.uuid4()))
        props_with_id = {**props, 'id': node_id}
        cypher = f"CREATE (n:{label} $props) RETURN n.id AS id"
        records = self._run_tx(cypher, {'props': props_with_id})
        if not records:
            raise RuntimeError(f"Échec de la création du nœud {label}")
        return records[0]['id']

    def create_scenario(
        self,
        nom: str,
        description: str,
        priorite: str,
        document_ids: Optional[List[str]] = None,
        variables: Optional[List[Dict[str, str]]] = None,
        etapes: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        doc_ids = document_ids or []
        vars_ = variables or []
        steps = etapes or []
        scenario_id = str(uuid.uuid4())
        cypher = (
            "CREATE (s:Scenario {"
            "id: $id, nom: $nom, description: $desc, dateCreation: datetime(), "
            "statut: 'actif', priorite: $prio, etapes: $etapes})"
            " RETURN s.id AS id"
        )
        # Convertir la liste d'étapes en JSON
        etapes_json = json.dumps(steps)

        # fetch list of records
        records = self._run_tx(cypher, {
            "id": scenario_id,
            "nom": nom,
            "desc": description,
            "prio": priorite,
            "etapes": etapes_json,  # Utiliser la version JSON
        })
        if not records:
            raise RuntimeError("Échec de la création du scénario")
        record = records[0]
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

    def create_and_link_variable_to_document(
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
        })[0]
        return record["id"]

    def start_automation(self, scenario_id: str, agent_config: Dict[str, Any]) -> str:
        automation_id = str(uuid.uuid4())
        cypher = (
            "MATCH (s:Scenario {id: $sid}) "
            "CREATE (a:Automatisation {"
            "id: $aid, dateExecution: datetime(), statut: 'queued', resultat: null, "
            "duree: 0, agent_config: $cfg})"
            "CREATE (a)-[:TRIGGERS]->(s) RETURN a.id AS id"
        )
        # serialize the config to a JSON string
        cfg_str = json.dumps(agent_config)
        records = self._run_tx(
            cypher,
            {"sid": scenario_id, "aid": automation_id, "cfg": cfg_str}
        )
        if not records:
            raise RuntimeError("Échec du démarrage de l'automatisation")
        return records[0]['id']

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

    def update_scenario(
        self, scenario_id: str, statut: str, resultat: Optional[str] = None
    ) -> None:
        """Met à jour le statut et le résultat d'un scénario existant"""
        # Optionally map human-readable statuses to internal values
        statut_map = {"en cours": "running",
                      "terminé": "success", "échoué": "error"}
        mapped_statut = statut_map.get(statut, statut)
        cypher = "MATCH (s:Scenario {id: $id}) SET s.statut = $stat"
        params = {"id": scenario_id, "stat": mapped_statut}
        if resultat is not None:
            cypher += ", s.resultat = $res"
            params["res"] = resultat
        self._run_tx(cypher, params)

    def get_scenario_with_relations(self, scenario_id: str) -> Dict[str, Any]:
        cypher = (
            "MATCH (s:Scenario {id: $id})"
            " OPTIONAL MATCH (s)-[r:USES_DOCUMENT]->(d:Document)"
            " OPTIONAL MATCH (s)-[r2:USES_VARIABLE]->(v:Variable)"
            " RETURN s AS scenario, collect(distinct d) AS documents, collect(distinct v) AS variables"
        )
        records = self._run_tx(cypher, {"id": scenario_id})
        if not records:
            return {}
        record = records[0]
        if not record:
            return {}

        # Récupérer le scénario et convertir en dictionnaire
        scenario_dict = dict(record["scenario"])

        # Désérialiser la chaîne JSON des étapes si elle existe
        if "etapes" in scenario_dict and isinstance(scenario_dict["etapes"], str):
            try:
                scenario_dict["etapes"] = json.loads(scenario_dict["etapes"])
            except:
                # En cas d'erreur de parsing, laisser tel quel
                pass

        return {
            "scenario": scenario_dict,
            "documents": [dict(d) for d in record["documents"]],
            "variables": [dict(v) for v in record["variables"]]
        }

    def get_document(self, document_id: str) -> Dict[str, Any]:
        cypher = "MATCH (d:Document {id: $id}) RETURN d"
        records = self._run_tx(cypher, {"id": document_id})
        if not records:
            return {}
        record = records[0]
        if not record:
            return {}
        return dict(record["d"])

    def check_duplicate_invoice(
        self, numero_facture: str, document_id: Optional[str] = None
    ) -> bool:
        """Vérifie si une facture existe déjà selon son numéro (optionnellement excluant un ID donné)."""
        cypher = (
            "MATCH (d:Document {type: 'facture'}) "
            "WHERE EXISTS((d)-[:HAS_VARIABLE]->(:Variable {key: 'numero_facture', value: $num}))"
        )
        params: Dict[str, Any] = {"num": numero_facture}
        if document_id:
            cypher += " AND d.id <> $did"
            params["did"] = document_id
        cypher += " RETURN count(d) > 0 AS dup"
        records = self._run_tx(cypher, params)
        if not records:
            return False
        return bool(records[0]["dup"])

    def update_scenario_etapes(self, scenario_id: str, etapes: List[Dict[str, Any]]) -> None:
        """
        Mets à jour la propriété `etapes` (JSON) du nœud Scenario.s
        """
        cypher = "MATCH (s:Scenario {id: $sid}) SET s.etapes = $etapes"
        self._run_tx(cypher, {"sid": scenario_id, "etapes": etapes})

    def link_nodes(self, from_lbl, from_id, rel, to_lbl, to_id, rel_props=None):
        """
        Méthode générique pour relier deux nœuds.
        """
        rp = ""
        params = {"from_id": from_id, "to_id": to_id}
        if rel_props:
            kv = ", ".join([f"{k}: ${k}" for k in rel_props])
            rp = f" {{ {kv} }}"
            params.update(rel_props)
        cypher = (
            f"MATCH (a:{from_lbl} {{id: $from_id}}), (b:{to_lbl} {{id: $to_id}}) "
            f"MERGE (a)-[r:{rel}{rp}]->(b)"
        )
        self._run_tx(cypher, params)

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
            records = self._run_tx("RETURN 1 AS ok")
            return bool(records and records[0].get("ok") == 1)
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

    def create_resultat_genere(self,
                               titre: str,
                               minio_key: str,
                               automatisation_id: str,
                               scenario_id: str,
                               type_resultat: str = "document",
                               variables_utilisees: List[str] = None,
                               metadonnees: Dict[str, Any] = None) -> str:
        """
        Crée un noeud ResultatGenere dans Neo4j et établit les relations avec l'Automatisation et le Scénario

        Args:
            titre: Titre du résultat généré
            minio_key: Clé MinIO du fichier résultat
            automatisation_id: ID de l'automatisation qui a généré ce résultat  
            scenario_id: ID du scénario associé
            type_resultat: Type de résultat (document, email, pdf...)
            variables_utilisees: Liste des IDs des variables utilisées
            metadonnees: Métadonnées supplémentaires à stocker

        Returns:
            ID du noeud ResultatGenere créé
        """
        resultat_id = str(uuid.uuid4())
        variables_utilisees = variables_utilisees or []
        metadonnees = metadonnees or {}

        # Création du noeud ResultatGenere
        query = """
        CREATE (r:ResultatGenere {
            id: $id,
            titre: $titre,
            minio_key: $minio_key,
            type: $type,
            date_creation: datetime(),
            metadonnees: $metadonnees
        })
        WITH r
        MATCH (a:Automatisation {id: $automatisation_id})
        MATCH (s:Scenario {id: $scenario_id})
        CREATE (a)-[:A_GENERE]->(r)
        CREATE (r)-[:LIE_A]->(s)
        RETURN r.id as id
        """

        params = {
            "id": resultat_id,
            "titre": titre,
            "minio_key": minio_key,
            "type": type_resultat,
            "automatisation_id": automatisation_id,
            "scenario_id": scenario_id,
            "metadonnees": json.dumps(metadonnees)
        }

        result = self._run_tx(query, params)

        # Lier aux variables utilisées si spécifiées
        if variables_utilisees:
            for var_id in variables_utilisees:
                self._run_tx("""
                MATCH (r:ResultatGenere {id: $resultat_id})
                MATCH (v:Variable {id: $var_id})
                CREATE (r)-[:UTILISE]->(v)
                """, {"resultat_id": resultat_id, "var_id": var_id})

        return resultat_id

    def get_resultats_pour_automatisation(self, automatisation_id: str) -> List[Dict[str, Any]]:
        """
        Récupère tous les résultats associés à une automatisation

        Args:
            automatisation_id: ID de l'automatisation

        Returns:
            Liste des résultats générés
        """
        query = """
        MATCH (a:Automatisation {id: $automatisation_id})-[:A_GENERE]->(r:ResultatGenere)
        RETURN r
        """

        results = self._run_tx(query, {"automatisation_id": automatisation_id})
        return [dict(result["r"]) for result in results]

    def get_resultats_pour_scenario(self, scenario_id: str) -> List[Dict[str, Any]]:
        """
        Récupère tous les résultats associés à un scénario

        Args:
            scenario_id: ID du scénario

        Returns:
            Liste des résultats générés
        """
        query = """
        MATCH (s:Scenario {id: $scenario_id})<-[:LIE_A]-(r:ResultatGenere)
        RETURN r
        """

        results = self._run_tx(query, {"scenario_id": scenario_id})
        return [dict(result["r"]) for result in results]


# Instance partagée pour l'application
# neo4j_driver = Neo4jDriver()
