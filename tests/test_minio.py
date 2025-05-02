import os
import sys
import pytest
from scripts.minio_manager import MinioManager
from src.config import config

@pytest.fixture(scope="module")
def minio_manager():
    minio_conf = config.get_minio_config()
    return MinioManager(
        endpoint=minio_conf["endpoint"],
        access_key=minio_conf["access_key"],
        secret_key=minio_conf["secret_key"],
        bucket=minio_conf["bucket"],
        secure=minio_conf["secure"]
    )

def test_upload_file(minio_manager):
    content = b"Test content"
    filename = "test.txt"
    result = minio_manager.upload_file(content, filename, "text/plain")
    assert result["filename"] == filename

def test_download_file(minio_manager):
    filename = "test.txt"
    downloaded = minio_manager.download_file(filename)
    assert downloaded.read() == b"Test content"