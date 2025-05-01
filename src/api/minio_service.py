import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from minio.error import S3Error

from scripts.minio_manager import MinioManager
from src.neo4j_driver import Neo4jDriver
from src.auth import verify_token, get_minio_manager, get_driver

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/upload/", dependencies=[Depends(verify_token)])
async def upload_file(
    file: UploadFile = File(...),
    type_doc: str = Form("autre"),
    statut: str = Form("actif"),
    minio_manager: MinioManager = Depends(get_minio_manager),
    driver: Neo4jDriver = Depends(get_driver),
):
    """Upload un fichier dans MinIO et créer un nœud Document dans Neo4j."""
    try:
        content = await file.read()
        result = minio_manager.upload_file(content, file.filename, file.content_type)
        doc_id = driver.create_document(
            titre=file.filename,
            type=type_doc,
            minio_key=file.filename,
            statut=statut
        )
        result["neo4j_doc_id"] = doc_id
        return result
    except S3Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download/{filename}", dependencies=[Depends(verify_token)])
def download_file(
    filename: str,
    minio_manager: MinioManager = Depends(get_minio_manager)
):
    """Télécharger un fichier depuis MinIO"""
    try:
        response = minio_manager.download_file(filename)
        return StreamingResponse(response, media_type="application/octet-stream")
    except S3Error:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
