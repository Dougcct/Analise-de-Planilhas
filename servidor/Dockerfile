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

# 2) código: o motor, a API, os templates e os MODELOS (.toml) usados na análise real
COPY src/ src/
COPY Agentes/ Agentes/
COPY servidor/ servidor/
COPY templates/ templates/
COPY assets/ assets/
COPY automacao/ automacao/
COPY config/modelos/ config/modelos/
# cópia-semente FORA do volume: config/modelos vira um volume (editável em runtime) e começa vazio,
# então o start semeia a partir daqui na 1ª vez (ver servidor.app._semear_modelos).
COPY config/modelos/ _seed_modelos/

# usuário sem privilégio (não rodar como root). A pasta das cargas é criada aqui com o dono certo,
# para o volume nomeado (montado nela) herdar a permissão de escrita do usuário app.
RUN useradd --create-home app && mkdir -p /app/dados_cargas && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/web/login', timeout=4)"

CMD ["uvicorn", "servidor.app:app", "--host", "0.0.0.0", "--port", "8000"]
