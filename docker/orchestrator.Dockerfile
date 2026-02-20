FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies (will be created in core/requirements.txt)
COPY ./core/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application logic
COPY ./core /app/core

EXPOSE 8000

# Start with reload for dev, can be adjusted for prod
CMD ["python", "core/main.py"]
