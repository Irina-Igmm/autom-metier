#!/usr/bin/env python3
"""
Script utilitaire pour générer un fichier .env à partir de .env.example
Évite de devoir copier manuellement le fichier.
"""

import os
import sys
import uuid
import shutil
from pathlib import Path

def main():
    """Génère un fichier .env à partir de .env.example."""
    root_dir = Path(__file__).parent.parent
    env_example = root_dir / ".env.example"
    env_file = root_dir / ".env"
    
    if not env_example.exists():
        print("Erreur: Le fichier .env.example n'existe pas!")
        sys.exit(1)
    
    if env_file.exists():
        overwrite = input("Le fichier .env existe déjà. Voulez-vous l'écraser? (o/n): ")
        if overwrite.lower() != 'o':
            print("Opération annulée.")
            sys.exit(0)
    
    # Copier le fichier
    shutil.copy(env_example, env_file)
    print(f"Fichier .env créé à partir de .env.example")
    
    # Générer une nouvelle clé secrète
    with open(env_file, 'r') as f:
        lines = f.readlines()
    
    with open(env_file, 'w') as f:
        for line in lines:
            if line.startswith('SECRET_KEY='):
                # Générer une nouvelle clé sécurisée
                new_key = uuid.uuid4().hex
                f.write(f'SECRET_KEY={new_key}\n')
            else:
                f.write(line)
    
    print("Configuration terminée! N'oubliez pas de mettre à jour les valeurs dans votre fichier .env.")
    print("Vous pouvez maintenant démarrer les services avec docker-compose.")


if __name__ == "__main__":
    main()