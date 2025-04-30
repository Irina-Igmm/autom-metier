import logging
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import StreamingResponse
from minio import Minio
from minio.error import S3Error
from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
from src.config import config

app = FastAPI()
logger = logging.getLogger(__name__)

# Initialisation du manager MinIO avec la config centralisée


def get_minio_manager():
    minio_conf = config.get_minio_config()
    return MinioManager(
        minio_conf["endpoint"],
        minio_conf["access_key"],
        minio_conf["secret_key"],
        minio_conf["bucket"],
        secure=minio_conf["secure"]
    )


minio_manager = get_minio_manager()


def get_driver():
    return Neo4jDriver()


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...), type_doc: str = "autre", statut: str = "actif", driver: Neo4jDriver = Depends(get_driver)):
    try:
        logger.info(f"Début upload fichier {file.filename} de type {type_doc}")
        content = await file.read()
        result = minio_manager.upload_file(content, file.filename, file.content_type)
        # Appel à Neo4j pour stocker les métadonnées du document
        doc_id = driver.create_document(
            titre=file.filename,
            type=type_doc,
            minio_key=file.filename,
            statut=statut
        )
        result["neo4j_doc_id"] = doc_id
        logger.info(
            f"Fichier uploadé avec succès: {file.filename}, Document ID: {doc_id}")
        return result
    except S3Error as e:
        logger.error(f"Erreur S3 lors de l'upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{filename}")
def download_file(filename: str):
    try:
        logger.info(f"Téléchargement du fichier {filename}")
        response = minio_manager.download_file(filename)
        return StreamingResponse(response, media_type="application/octet-stream")
    except S3Error as e:
        logger.error(f"Erreur S3 lors du téléchargement: {e}")
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
