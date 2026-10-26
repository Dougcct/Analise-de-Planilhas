# Imagem do SERVIDOR v2 (API FastAPI + motor de análise). Contexto de build = raiz do projeto
# (precisa de src/ e servidor/):  docker compose build   ou   docker build -f servidor/Dockerfile .
FROM python:3.12-slim

# Python previsível em contêiner: sem .pyc, saída sem buffer (logs na hora)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) dependências primeiro (camada reaproveitada enquanto o requirements não muda)
COPY servidor/requirements.txt servidor/requirements.txt
RUN pip install -r servidor/requirements.txt

# 2) código: o motor e a API
COPY src/ src/
COPY servidor/ servidor/

# usuário sem privilégio (não rodar como root)
RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/status/versao', timeout=4)"

CMD ["uvicorn", "servidor.app:app", "--host", "0.0.0.0", "--port", "8000"]
