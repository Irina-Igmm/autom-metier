# Schéma Neo4j pour l'automatisation de scénarios métier

## Modèle de données

Notre système d'automatisation de scénarios métier utilise Neo4j pour modéliser les relations entre les différents éléments qui composent un scénario métier. Nous définissons quatre types principaux de nœuds:

### Nœuds

1. **Document**
   - Représente un document physique ou numérique impliqué dans un scénario
   - Propriétés:
     - `id`: Identifiant unique (UUID)
     - `nom`: Nom du document
     - `type`: Type du document (ex: facture, contrat, email)
     - `chemin`: Chemin MinIO où le document est stocké
     - `dateCreation`: Date de création
     - `statut`: Statut du document (ex: actif, archivé)

2. **Variable**
   - Représente une donnée extraite ou utilisée dans un scénario
   - Propriétés:
     - `id`: Identifiant unique (UUID)
     - `nom`: Nom de la variable
     - `type`: Type de données (ex: string, date, number, boolean)
     - `valeur`: Valeur de la variable
     - `dateExtraction`: Date d'extraction
     - `confiance`: Score de confiance (0-1) pour les valeurs extraites par l'IA

3. **Scenario**
   - Représente un workflow d'automatisation métier
   - Propriétés:
     - `id`: Identifiant unique (UUID)
     - `nom`: Nom du scénario
     - `description`: Description détaillée
     - `dateCreation`: Date de création
     - `statut`: Statut du scénario (ex: actif, inactif)
     - `priorite`: Niveau de priorité (ex: haute, moyenne, basse)

4. **Automatisation**
   - Représente une instance d'exécution d'un scénario
   - Propriétés:
     - `id`: Identifiant unique (UUID)
     - `dateExecution`: Date d'exécution
     - `statut`: Statut de l'exécution (ex: en cours, terminé, échoué)
     - `resultat`: Description du résultat
     - `duree`: Durée d'exécution en secondes

### Relations

1. **UTILISE**
   - Connecte un Scénario à un Document ou une Variable
   - Direction: `(Scenario)-[:UTILISE]->(Document|Variable)`
   - Propriétés:
     - `role`: Rôle du document ou de la variable (ex: entrée, référence)

2. **GÉNÈRE**
   - Connecte un Scénario à un Document ou une Variable créé dans le processus
   - Direction: `(Scenario)-[:GÉNÈRE]->(Document|Variable)`
   - Propriétés:
     - `type`: Type de génération (ex: création, modification)

3. **LIÉE_À**
   - Connecte un Document à une Variable extraite de ce document
   - Direction: `(Document)-[:LIÉE_À]->(Variable)`
   - Propriétés:
     - `method`: Méthode d'extraction (ex: IA, règle, utilisateur)
     - `confidence`: Score de confiance pour l'extraction

4. **EXÉCUTION_DE**
   - Connecte une Automatisation à un Scénario
   - Direction: `(Automatisation)-[:EXÉCUTION_DE]->(Scenario)`

## Contraintes d'unicité

Pour garantir l'intégrité des données, nous définissons les contraintes suivantes:

```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (v:Variable) REQUIRE v.id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (s:Scenario) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (a:Automatisation) REQUIRE a.id IS UNIQUE;
```

## Requêtes Cypher principales

### Création d'un scénario avec documents et variables

```cypher
// Création d'un scénario
CREATE (s:Scenario {
  id: $scenarioId,
  nom: $nom,
  description: $description,
  dateCreation: datetime(),
  statut: "actif",
  priorite: $priorite
})

// Connexion à des documents existants
MATCH (d:Document)
WHERE d.id IN $documentIds
CREATE (s)-[:UTILISE {role: "entrée"}]->(d)

// Définition des variables attendues
WITH s
UNWIND $variables AS var
CREATE (v:Variable {
  id: randomUUID(),
  nom: var.nom,
  type: var.type,
  valeur: null,
  dateExtraction: null,
  confiance: null
})
CREATE (s)-[:UTILISE {role: "extraire"}]->(v)
```

### Vérification des doublons (exemple pour factures)

```cypher
// Vérifier si une facture similaire existe déjà
MATCH (d:Document {type: "facture"})
WHERE d.id <> $documentId
  AND EXISTS((d)-[:LIÉE_À]->(:Variable {nom: "numeroFacture", valeur: $numeroFacture}))
  AND EXISTS((d)-[:LIÉE_À]->(:Variable {nom: "fournisseur", valeur: $fournisseur}))
RETURN d
```

### Récupération d'un scénario avec ses relations

```cypher
// Récupérer un scénario avec ses documents et variables
MATCH (s:Scenario {id: $scenarioId})
OPTIONAL MATCH (s)-[r:UTILISE|GÉNÈRE]->(d:Document)
OPTIONAL MATCH (s)-[r2:UTILISE|GÉNÈRE]->(v:Variable)
OPTIONAL MATCH (d)-[r3:LIÉE_À]->(v)
RETURN s, r, d, r2, v, r3
```

### Création d'une automatisation

```cypher
// Démarrer une exécution d'automatisation
MATCH (s:Scenario {id: $scenarioId})
CREATE (a:Automatisation {
  id: randomUUID(),
  dateExecution: datetime(),
  statut: "en cours",
  resultat: null,
  duree: 0
})
CREATE (a)-[:EXÉCUTION_DE]->(s)
RETURN a.id as automatisationId
```

### Mise à jour du statut d'une automatisation

```cypher
// Mettre à jour le statut d'une automatisation
MATCH (a:Automatisation {id: $automatisationId})
SET a.statut = $statut, 
    a.resultat = $resultat,
    a.duree = $duree
RETURN a
```