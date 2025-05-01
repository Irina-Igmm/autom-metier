"""
Module d'authentification pour l'API
"""
from datetime import datetime, timedelta
from typing import Generator

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from src.neo4j_driver import Neo4jDriver
from src.config import Config as config
from scripts.minio_manager import MinioManager

# Sécurité pour Bearer token
security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Vérifie la validité du JWT token"""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, config.SECRET_KEY or config.VAR_SYS, algorithms=["HS256"]
        )
        subject: str = payload.get("sub")
        if subject != config.VAR_SYS:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return subject


def get_driver(current_user: str = Depends(verify_token)) -> Generator[Neo4jDriver, None, None]:
    """Récupère une instance du driver Neo4j"""
    driver = Neo4jDriver()
    try:
        yield driver
    finally:
        driver.close()


def get_minio_manager(current_user: str = Depends(verify_token)) -> MinioManager:
    """Récupère une instance du manager MinIO"""
    minio_conf = config.get_minio_config()
    mgr = MinioManager(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        bucket=config.MINIO_BUCKET,
        secure=config.MINIO_SECURE,
    )
    mgr.current_user = current_user
    return mgr


def generate_token():
    """Génère un nouveau token JWT"""
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": config.VAR_SYS,
        "exp": expire
    }
    token = jwt.encode(
        payload, config.SECRET_KEY or config.VAR_SYS, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_at": expire.isoformat()}