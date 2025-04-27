"""
Module pour la gestion des connexions et requêtes Neo4j.
Fournit une interface pour interagir avec la base de données graphe.
"""

import uuid
from typing import Dict, List, Any

from neo4j import GraphDatabase, Driver
from .config import config

class Neo4jDriver:
    """Gestionnaire de connexion et requêtes Neo4j."""

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        """
        Initialise une connexion à Neo4j.
        
        Args:
            uri: URI de connexion Neo4j (par défaut: depuis config)
            user: Nom d'utilisateur Neo4j (par défaut: depuis config)
            password: Mot de passe Neo4j (par défaut: depuis config)
        """
        self.uri = uri or config.NEO4J_URI
        self.user = user or config.NEO4J_USER
        self.password = password or config.NEO4J_PASSWORD
        self.driver: Driver = None
        self.connect()
        # Créer automatiquement les contraintes d'unicité si elles n'existent pas
        try:
            self.create_constraints()
        except Exception as e:
            print(f"Échec de la création des contraintes Neo4j: {e}")

    def connect(self) -> None:
        """Établit la connexion à Neo4j."""
        self.driver = GraphDatabase.driver(
            self.uri, auth=(self.user, self.password)
        )
        # Vérification de la connexion
        with self.driver.session() as session:
            result = session.run("MATCH () RETURN count(*) as count")
            records = list(result)
            print(f"Connexion établie à Neo4j. {records[0]['count']} nœuds existants.")

    def close(self) -> None:
        """Ferme la connexion à Neo4j."""
        if self.driver:
            self.driver.close()
            self.driver = None

    def create_constraints(self) -> None:
        """
        Crée les contraintes d'unicité sur les nœuds principaux.
        À exécuter une seule fois lors de l'initialisation de la base.
        """
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (v:Variable) REQUIRE v.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Scenario) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Automatisation) REQUIRE a.id IS UNIQUE",
        ]
        with self.driver.session() as session:
            for constraint in constraints:
                session.run(constraint)
            print("Contraintes Neo4j créées avec succès")

    def create_scenario(
        self, nom: str, description: str, priorite: str, document_ids: List[str] = None, 
        variables: List[Dict[str, str]] = None
    ) -> str:
        """
        Crée un nouveau scénario avec ses relations vers documents et variables.
        
        Args:
            nom: Nom du scénario
            description: Description détaillée
            priorite: Niveau de priorité ("haute", "moyenne", "basse")
            document_ids: Liste d'IDs de documents existants à lier
            variables: Liste de variables à créer et lier 
                       [{nom: "nom_var", type: "type_var"}, ...]
        
        Returns:
            ID du scénario créé
        """
        scenario_id = str(uuid.uuid4())
        document_ids = document_ids or []
        variables = variables or []
        
        query = """
        // Création du scénario
        CREATE (s:Scenario {
            id: $scenario_id,
            nom: $nom,
            description: $description,
            dateCreation: datetime(),
            statut: "actif",
            priorite: $priorite
        })
        
        // Retourne l'identifiant
        RETURN s.id as id
        """
        
        with self.driver.session() as session:
            # Créer le scénario
            result = session.run(
                query, 
                scenario_id=scenario_id,
                nom=nom,
                description=description,
                priorite=priorite
            )
            scenario_id = result.single()["id"]
            
            # Connecter documents existants si présents
            if document_ids:
                session.run("""
                MATCH (s:Scenario {id: $scenario_id})
                MATCH (d:Document)
                WHERE d.id IN $document_ids
                CREATE (s)-[:UTILISE {role: "entrée"}]->(d)
                """, scenario_id=scenario_id, document_ids=document_ids)
            
            # Créer et connecter variables si présentes
            if variables:
                for var in variables:
                    var_id = str(uuid.uuid4())
                    session.run("""
                    MATCH (s:Scenario {id: $scenario_id})
                    CREATE (v:Variable {
                        id: $var_id,
                        nom: $nom,
                        type: $type,
                        valeur: null,
                        dateExtraction: null,
                        confiance: null
                    })
                    CREATE (s)-[:UTILISE {role: "extraction"}]->(v)
                    """, scenario_id=scenario_id, var_id=var_id, nom=var["nom"], type=var["type"])
                    
        return scenario_id

    def create_document(
        self, nom: str, type_doc: str, chemin: str, statut: str = "actif"
    ) -> str:
        """
        Crée un nouveau document dans Neo4j.
        
        Args:
            nom: Nom du document
            type_doc: Type du document (facture, contrat, email, etc.)
            chemin: Chemin MinIO où le document est stocké
            statut: Statut du document (actif, archivé, etc.)
            
        Returns:
            ID du document créé
        """
        document_id = str(uuid.uuid4())
        
        query = """
        CREATE (d:Document {
            id: $id,
            nom: $nom,
            type: $type_doc,
            minio_key: $chemin,
            dateCreation: datetime(),
            statut: $statut
        })
        RETURN d.id as id
        """
        
        with self.driver.session() as session:
            result = session.run(
                query,
                id=document_id,
                nom=nom,
                type_doc=type_doc,
                chemin=chemin,
                statut=statut
            )
            return result.single()["id"]

    def link_variable_to_document(
        self, document_id: str, variable_nom: str, variable_valeur: Any, 
        variable_type: str = "string", methode: str = "IA", confiance: float = 1.0
    ) -> str:
        """
        Crée une variable et la relie à un document existant.
        
        Args:
            document_id: ID du document source
            variable_nom: Nom de la variable
            variable_valeur: Valeur extraite
            variable_type: Type de la variable
            methode: Méthode d'extraction (IA, règle, utilisateur)
            confiance: Score de confiance (0-1)
            
        Returns:
            ID de la variable créée
        """
        variable_id = str(uuid.uuid4())
        
        query = """
        MATCH (d:Document {id: $document_id})
        CREATE (v:Variable {
            id: $variable_id,
            nom: $nom,
            type: $type,
            valeur: $valeur,
            dateExtraction: datetime(),
            confiance: $confiance
        })
        CREATE (d)-[:LIÉE_À {method: $methode, confidence: $confiance}]->(v)
        RETURN v.id as id
        """
        
        with self.driver.session() as session:
            result = session.run(
                query,
                document_id=document_id,
                variable_id=variable_id,
                nom=variable_nom,
                type=variable_type,
                valeur=variable_valeur,
                methode=methode,
                confiance=confiance
            )
            return result.single()["id"]

    def start_automation(self, scenario_id: str) -> str:
        """
        Démarre une nouvelle automatisation pour un scénario.
        
        Args:
            scenario_id: ID du scénario à exécuter
            
        Returns:
            ID de l'automatisation créée
        """
        query = """
        MATCH (s:Scenario {id: $scenario_id})
        CREATE (a:Automatisation {
            id: randomUUID(),
            dateExecution: datetime(),
            statut: "en cours",
            resultat: null,
            duree: 0
        })
        CREATE (a)-[:EXÉCUTION_DE]->(s)
        RETURN a.id as id
        """
        
        with self.driver.session() as session:
            result = session.run(query, scenario_id=scenario_id)
            return result.single()["id"]

    def update_automation_status(
        self, automation_id: str, statut: str, resultat: str = None, duree: int = None
    ) -> None:
        """
        Met à jour le statut d'une automatisation.
        
        Args:
            automation_id: ID de l'automatisation
            statut: Nouveau statut (en cours, terminé, échoué)
            resultat: Description du résultat (optionnel)
            duree: Durée d'exécution en secondes (optionnel)
        """
        query = """
        MATCH (a:Automatisation {id: $id})
        SET a.statut = $statut
        """
        
        params = {"id": automation_id, "statut": statut}
        
        if resultat is not None:
            query += ", a.resultat = $resultat"
            params["resultat"] = resultat
            
        if duree is not None:
            query += ", a.duree = $duree"
            params["duree"] = duree
        
        with self.driver.session() as session:
            session.run(query, **params)

    def get_scenario_with_relations(self, scenario_id: str) -> Dict[str, Any]:
        """
        Récupère un scénario avec ses documents et variables associés.
        
        Args:
            scenario_id: ID du scénario à récupérer
            
        Returns:
            Dictionnaire contenant le scénario, ses documents et ses variables
        """
        query = """
        MATCH (s:Scenario {id: $id})
        OPTIONAL MATCH (s)-[r:UTILISE|GÉNÈRE]->(d:Document)
        OPTIONAL MATCH (s)-[r2:UTILISE|GÉNÈRE]->(v:Variable)
        RETURN s, collect(distinct {doc: d, rel: r}) as documents, 
               collect(distinct {var: v, rel: r2}) as variables
        """
        
        with self.driver.session() as session:
            result = session.run(query, id=scenario_id)
            record = result.single()
            if not record:
                return None
                
            scenario = dict(record["s"])
            
            documents = []
            for doc_data in record["documents"]:
                if doc_data["doc"] is not None:
                    doc = dict(doc_data["doc"])
                    rel = dict(doc_data["rel"])
                    doc["relation"] = rel
                    documents.append(doc)
            
            variables = []
            for var_data in record["variables"]:
                if var_data["var"] is not None:
                    var = dict(var_data["var"])
                    rel = dict(var_data["rel"])
                    var["relation"] = rel
                    variables.append(var)
            
            return {
                "scenario": scenario,
                "documents": documents,
                "variables": variables
            }

    def check_duplicate_invoice(self, num_facture: str, fournisseur: str, document_id: str = None) -> bool:
        """
        Vérifie si une facture similaire existe déjà.
        
        Args:
            num_facture: Numéro de facture
            fournisseur: Nom du fournisseur
            document_id: ID du document à exclure (optionnel)
            
        Returns:
            True si un doublon existe, False sinon
        """
        query = """
        MATCH (d:Document {type: "facture"})
        WHERE EXISTS((d)-[:LIÉE_À]->(:Variable {nom: "numeroFacture", valeur: $num}))
          AND EXISTS((d)-[:LIÉE_À]->(:Variable {nom: "fournisseur", valeur: $fournisseur}))
        """
        
        if document_id:
            query += " AND d.id <> $doc_id"
            
        query += " RETURN count(d) > 0 as exists"
        
        with self.driver.session() as session:
            result = session.run(
                query, 
                num=num_facture,
                fournisseur=fournisseur,
                doc_id=document_id
            )
            return result.single()["exists"]

    def link_scenario_to_document(self, scenario_id: str, document_id: str, role: str = "entrée") -> None:
        """
        Crée une relation UTILISE entre un scénario et un document.
        """
        query = """
        MATCH (s:Scenario {id: $scenario_id}), (d:Document {id: $document_id})
        MERGE (s)-[:UTILISE {role: $role}]->(d)
        """
        with self.driver.session() as session:
            session.run(query, scenario_id=scenario_id, document_id=document_id, role=role)

    def link_scenario_to_variable(self, scenario_id: str, variable_id: str, role: str = "extraction") -> None:
        """
        Crée une relation UTILISE entre un scénario et une variable.
        """
        query = """
        MATCH (s:Scenario {id: $scenario_id}), (v:Variable {id: $variable_id})
        MERGE (s)-[:UTILISE {role: $role}]->(v)
        """
        with self.driver.session() as session:
            session.run(query, scenario_id=scenario_id, variable_id=variable_id, role=role)


# Utilisation comme singleton
neo4j_driver = Neo4jDriver()

# # Exemple d'utilisation:
# if __name__ == "__main__":
#     # Ce code s'exécute uniquement si le module est exécuté directement
#     driver = Neo4jDriver()
#     driver.create_constraints()
#     driver.close()