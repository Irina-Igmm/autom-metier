from typing import Any, Dict
from src.neo4j_driver import Neo4jDriver


class Neo4jTool:
    def __init__(self):
        self.driver = Neo4jDriver()

    def run_query(self, cypher: str, params: Dict[str, Any] = None) -> Any:
        """Exécute une requête Cypher et retourne le résultat brut."""
        return self.driver._run_tx(cypher, params)

    def create_node(self, label: str, properties: Dict[str, Any]) -> str:
        """Crée un nœud et retourne son ID."""
        props = ", ".join([f"{k}: ${k}" for k in properties])
        cypher = f"CREATE (n:{label} {{ {props} }}) RETURN n.id AS id"
        record = self.run_query(cypher, properties).single()
        return record['id']

    def link_nodes(self, from_label: str, from_id: str, rel: str, to_label: str, to_id: str, rel_props: Dict[str, Any] = None) -> None:
        """Crée une relation entre deux nœuds."""
        rp = ''
        if rel_props:
            kv = ", ".join([f"{k}: ${k}" for k in rel_props])
            rp = f" {{ {kv} }}"
        cypher = (
            f"MATCH (a:{from_label} {{id: $aid}}), (b:{to_label} {{id: $bid}}) "
            f"MERGE (a)-[r:{rel}{rp}]->(b)"
        )
        params = {'aid': from_id, 'bid': to_id}
        if rel_props:
            params.update(rel_props)
        self.run_query(cypher, params)
