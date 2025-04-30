import io
from minio import Minio
from minio.error import S3Error


class MinioManager:
    def __init__(self, endpoint, access_key, secret_key, bucket, secure=False):
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        self.bucket = bucket
        self.ensure_bucket()

    def ensure_bucket(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as e:
            print(f"S3Error in ensure_bucket: {e}")
            raise

    def upload_file(self, file_obj, filename, content_type):
        try:
            # Toujours obtenir un objet fichier pour MinIO
            if hasattr(file_obj, 'read'):
                content = file_obj.read()
            else:
                content = file_obj
            # On passe un BytesIO à put_object
            self.client.put_object(
                self.bucket,
                filename,
                data=io.BytesIO(content),
                length=len(content),
                content_type=content_type
            )
            return {"filename": filename, "bucket": self.bucket}
        except S3Error as e:
            print(f"S3Error in upload_file: {e}")
            raise

    def download_file(self, filename):
        try:
            return self.client.get_object(self.bucket, filename)
        except S3Error as e:
            print(f"S3Error in download_file: {e}")
            raise
