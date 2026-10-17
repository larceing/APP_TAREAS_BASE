FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# mariadb-client: mariadb-dump para "Hacer backup ahora" (Configuracion -> Copias de seguridad)
RUN apt-get update \
    && apt-get install -y --no-install-recommends mariadb-client \
    && rm -rf /var/lib/apt/lists/*

COPY app_fastapi/requirements.txt app_fastapi/requirements.txt
RUN pip install -r app_fastapi/requirements.txt

COPY app_fastapi app_fastapi
COPY scripts scripts
COPY docs docs
# compose del despliegue por entornos: tareas.sh lo saca de cada version
COPY despliegue/servidor despliegue/servidor

# version de la imagen (la pone GitHub Actions: v1.2.0, sha-1a2b3c4...)
ARG APP_VERSION=local
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

# datos que deben sobrevivir al contenedor (volumenes en docker-compose.yml)
RUN mkdir -p data media app_fastapi/logs .cache

EXPOSE 8000

# 1) instala la BD si aun no existe (idempotente) 2) arranca la app
CMD ["sh", "-c", "python scripts/instalar.py --esperar 90 && exec uvicorn app_fastapi.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
