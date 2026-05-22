# E18.T1 — Dockerfile para el servicio de fine-tuning
#
# Build sin GPU (CPU only — producción):
#   docker compose run fine_tuning python fine_tuning/train.py --task narrative
#
# Build con GPU (si hay CUDA disponible, descomenta la línea FROM de abajo):
#   Cambia la primera línea a:  FROM nvidia/cuda:12.1.0-devel-ubuntu22.04
#   y agrega: RUN pip install unsloth[colab-new]

FROM python:3.11-slim

# Dependencias del sistema necesarias para psycopg2 y compilación
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        git \
        curl \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python — PyTorch CPU, transformers, trl, peft, psycopg2
# Nota: para GPU, reemplaza torch por la versión CUDA correspondiente:
#   pip install torch --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir \
    torch==2.3.1 \
    torchvision==0.18.1 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    transformers==4.44.2 \
    trl==0.10.1 \
    peft==0.12.0 \
    datasets==2.21.0 \
    accelerate==0.34.2 \
    bitsandbytes==0.43.3 \
    sentencepiece==0.2.0 \
    psycopg2-binary==2.9.9 \
    structlog==24.4.0 \
    redis==5.0.8

# Intentar instalar unsloth (falla silenciosamente en CPU — train.py usa fallback)
RUN pip install --no-cache-dir "unsloth[colab-new]" 2>/dev/null || true

# Copiar el código fuente
COPY . /app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Por defecto muestra la ayuda; el operador especifica el comando completo
CMD ["python", "fine_tuning/train.py", "--help"]
