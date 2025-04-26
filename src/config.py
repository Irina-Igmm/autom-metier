"""
Configuration centralisée pour l'application d'automatisation de scénarios métier.
Gère l'accès aux variables d'environnement et autres paramètres.
"""

import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

class Config:
    """Classe de configuration centralisée pour l'application."""
    
    # Configuration FastAPI
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8000"))
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    
    # Configuration Neo4j
    NEO4J_URI_LOCAL = os.getenv("NEO4J_URI_LOCAL", "bolt://localhost:7687")
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
    
    # Configuration MinIO
    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "documents")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
    
    # Configuration LLM/IA
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama3-8b-8192")
    
    # Configuration générale
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    TIMEOUT = int(os.getenv("TIMEOUT", "30"))
    
    @classmethod
    def get_neo4j_uri(cls):
        """
        Retourne l'URI Neo4j adaptée au contexte :
        - Si RUN_LOCAL=1 dans l'env, utilise NEO4J_URI_LOCAL (localhost)
        - Sinon, utilise NEO4J_URI (docker/service)
        """
        if os.getenv("RUN_LOCAL") == "1":
            return cls.NEO4J_URI_LOCAL
        return cls.NEO4J_URI

    @classmethod
    def get_neo4j_config(cls):
        """Retourne la configuration Neo4j sous forme de dictionnaire."""
        return {
            "uri": cls.get_neo4j_uri(),
            "user": cls.NEO4J_USER,
            "password": cls.NEO4J_PASSWORD
        }
    
    @classmethod
    def get_minio_config(cls):
        """Retourne la configuration MinIO sous forme de dictionnaire."""
        return {
            "endpoint": cls.MINIO_ENDPOINT,
            "access_key": cls.MINIO_ACCESS_KEY,
            "secret_key": cls.MINIO_SECRET_KEY,
            "secure": cls.MINIO_SECURE,
            "bucket": cls.MINIO_BUCKET
        }
    
    @classmethod
    def get_llm_config(cls):
        """Retourne la configuration du modèle LLM sous forme de dictionnaire."""
        return {
            "provider": cls.LLM_PROVIDER,
            "api_key": cls.LLM_API_KEY,
            "model": cls.LLM_MODEL
        }


config = Config()  # Instance singleton pour import direct

if __name__ == "__main__":
    # Affiche la configuration (sans secrets) pour débogage
    print(f"API: {config.API_HOST}:{config.API_PORT}")
    print(f"Neo4j: {config.get_neo4j_uri()} (user: {config.NEO4J_USER})")
    print(f"MinIO: {config.MINIO_ENDPOINT} (bucket: {config.MINIO_BUCKET})")
    print(f"LLM: {config.LLM_PROVIDER} ({config.LLM_MODEL})")
    print(f"LOG_LEVEL: {config.LOG_LEVEL}")
    print(f"TIMEOUT: {config.TIMEOUT} secondes")
