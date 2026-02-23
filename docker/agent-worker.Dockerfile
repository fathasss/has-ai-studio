FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    wget \
    unzip \
    xz-utils \
    build-essential \
    python3-dev \
    libicu-dev \
    libssl-dev \
    zlib1g-dev \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet \
    && pip install --no-cache-dir django \
    && rm -rf /var/lib/apt/lists/*

# Reuse orchestrator logic/dependencies or specific worker deps
COPY ./core/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application logic (we will use the same core logic for worker communication)
COPY ./core /app/core

CMD ["python", "core/main.py"]
