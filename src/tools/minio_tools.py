# src/tools/.pyminio_tools (suite)
from typing import Dict
from scripts.minio_manager import MinioManager
from src.config import config


class MinIOTool:
    def __init__(self):
        self.client = MinioManager(
            endpoint=config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            bucket=config.MINIO_BUCKET,
            secure=config.MINIO_SECURE,
        )

    def upload(self, content: bytes, filename: str, content_type: str) -> Dict[str, str]:
        """
        Upload un fichier sur MinIO et retourne la clé.
        """
        result = self.client.upload_file(content, filename, content_type)
        return {'bucket': result['bucket'], 'key': filename}

    def download(self, key: str) -> bytes:
        """
        Télécharge un fichier depuis MinIO et retourne les bytes.
        """
        return self.client.download_file(key).read()
