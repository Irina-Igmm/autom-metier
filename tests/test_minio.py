import os
import sys
import unittest
from io import BytesIO
import socket
from unittest.mock import patch, MagicMock

# Ajout du répertoire parent au path pour pouvoir importer les modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.minio_manager import MinioManager
from src.config import config

def is_minio_reachable(host, port, timeout=1):
    """Vérifie si le serveur MinIO est accessible."""
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except (socket.timeout, socket.error):
        return False

class TestMinioManager(unittest.TestCase):
    """Tests pour la classe MinioManager"""
    
    def setUp(self):
        """Configure l'instance MinioManager pour les tests."""
        minio_conf = config.get_minio_config()
        
        # Extraire le host et le port de l'endpoint
        endpoint = minio_conf["endpoint"]
        if ":" in endpoint:
            host, port_str = endpoint.split(":")
            port = int(port_str)
        else:
            host = endpoint
            port = 9000  # Port par défaut de MinIO
            
        # Vérifier si MinIO est accessible
        self.minio_available = is_minio_reachable(host, port)
        
        # Procéder avec la configuration de MinioManager
        self.minio_manager = MinioManager(
            minio_conf["endpoint"],
            minio_conf["access_key"],
            minio_conf["secret_key"],
            minio_conf["bucket"],
            secure=minio_conf["secure"]
        )
        
        # Définir le chemin vers le fichier de test
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.project_root, "data")
        self.test_file_path = os.path.join(self.data_dir, "facture_template_1.pdf")
        
        # Vérifier que le fichier existe
        if not os.path.exists(self.test_file_path):
            # Créer un contenu de test si le fichier n'existe pas
            self.test_content = b"Contenu de test pour MinioManager"
            print(f"Fichier de test '{self.test_file_path}' non trouvé. Utilisation d'un contenu de test par défaut.")
        else:
            # Lire le contenu du fichier
            with open(self.test_file_path, 'rb') as f:
                self.test_content = f.read()
            print(f"Fichier de test '{self.test_file_path}' chargé. Taille: {len(self.test_content)} octets")
        
        self.test_filename = "facture_template_1.pdf"
        self.test_content_type = "application/pdf"
    
    def test_connection(self):
        """Teste la connexion à MinIO et l'existence du bucket."""
        if not self.minio_available:
            self.skipTest("MinIO server is not available. Skipping test.")
            
        # Vérifie que le bucket existe (ensure_bucket est appelé dans __init__)
        self.assertTrue(self.minio_manager.client.bucket_exists(self.minio_manager.bucket))
        print(f"✓ Connexion à MinIO établie et bucket '{self.minio_manager.bucket}' vérifié.")
    
    def test_upload_download(self):
        """Teste le chargement et le téléchargement d'un fichier."""
        if not self.minio_available:
            self.skipTest("MinIO server is not available. Skipping test.")
        
        # Chargement du fichier
        result = self.minio_manager.upload_file(
            self.test_content, 
            self.test_filename,
            self.test_content_type
        )
        
        # Vérifie que le résultat contient les informations correctes
        self.assertEqual(result["filename"], self.test_filename)
        self.assertEqual(result["bucket"], self.minio_manager.bucket)
        print(f"✓ Fichier '{self.test_filename}' chargé avec succès dans le bucket '{result['bucket']}'.")
        
        try:
            # Téléchargement du fichier
            downloaded = self.minio_manager.download_file(self.test_filename)
            print(f"Type of downloaded object: {type(downloaded)}")
            # Lire le contenu du flux pour comparer aux bytes d'origine
            content = downloaded.read()
            self.assertEqual(content, self.test_content)
            print(f"✓ Fichier '{self.test_filename}' téléchargé avec succès. Contenu vérifié.")
        except Exception as e:
            print(f"Erreur lors du téléchargement: {type(e).__name__}: {str(e)}")
            raise
        
if __name__ == "__main__":
    unittest.main()