# Dockerfile pour FastAPI
FROM python:3.10-slim-bullseye

WORKDIR /app

# Copier les fichiers nécessaires
COPY ./src ./src
COPY ./scripts/wait_for_neo4j.py ./scripts/wait_for_neo4j.py
COPY ./main.py ./main.py
COPY requirements.txt ./requirements.txt

# Installation des dépendances
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    chmod +x ./scripts/wait_for_neo4j.py

EXPOSE 8000

# Utilisation du script d'attente
CMD ["python", "./scripts/wait_for_neo4j.py", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
