FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Reuse orchestrator logic/dependencies or specific worker deps
COPY ./core/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application logic (we will use the same core logic for worker communication)
COPY ./core /app/core

CMD ["python", "core/main.py"]
