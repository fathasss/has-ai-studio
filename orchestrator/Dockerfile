FROM python:3.11-slim

WORKDIR /app

# 🔥 TÜM PY DOSYALARINI KOPYALA
COPY . .

RUN pip install flask flask-cors requests

CMD ["python", "main.py"]
