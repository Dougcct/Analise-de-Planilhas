# Imagem do SERVIDOR v2 (API FastAPI + motor de análise). Contexto de build = raiz do projeto
# (precisa de src/ e servidor/):  docker compose build   ou   docker build -f servidor/Dockerfile .
FROM python:3.12-slim

# Python previsível em contêiner: sem .pyc, saída sem buffer (logs na hora)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libs nativas do WeasyPrint (PDF dos relatórios): Pango/Cairo/GDK-PixBuf + fontes
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 libffi8 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Oracle Instant Client (modo THICK do oracledb) — autentica contas do MV cujo verificador de senha
# o modo thin recusa (erro DPY-3015). "Basic Light" é a variante menor. A conexão só é usada na rede
# local (tela ADM «Consulta SQL»). libaio = dependência nativa do client.
ENV ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient
RUN apt-get update && apt-get install -y --no-install-recommends wget unzip ca-certificates \
    && (apt-get install -y --no-install-recommends libaio1t64 \
        || apt-get install -y --no-install-recommends libaio1) \
    && ( [ -e /usr/lib/x86_64-linux-gnu/libaio.so.1 ] \
        || ln -s libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 ) \
    && wget -q https://download.oracle.com/otn_software/linux/instantclient/instantclient-basiclite-linuxx64.zip \
         -O /tmp/instantclient.zip \
    && mkdir -p /opt/oracle \
    && unzip -q /tmp/instantclient.zip -d /opt/oracle \
    && ln -s /opt/oracle/instantclient_* "$ORACLE_CLIENT_LIB_DIR" \
    && echo "$ORACLE_CLIENT_LIB_DIR" > /etc/ld.so.conf.d/oracle-instantclient.conf && ldconfig \
    && rm /tmp/instantclient.zip \
    && apt-get purge -y wget unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# 1) dependências primeiro (camada reaproveitada enquanto o requirements não muda)
COPY servidor/requirements.txt servidor/requirements.txt
RUN pip install -r servidor/requirements.txt

# 2) código: o motor, a API, os templates e os MODELOS (.toml) usados na análise real
COPY src/ src/
COPY dominio/Agentes/ dominio/Agentes/
COPY servidor/ servidor/
COPY templates/ templates/
COPY assets/ assets/
COPY automacao/ automacao/
COPY dominio/modelos/ dominio/modelos/
# cópia-semente FORA do volume: dominio/modelos vira um volume (editável em runtime) e começa vazio,
# então o start semeia a partir daqui na 1ª vez (ver servidor.app._semear_modelos).
COPY dominio/modelos/ _seed_modelos/

# usuário sem privilégio (não rodar como root). A pasta das cargas é criada aqui com o dono certo,
# para o volume nomeado (montado nela) herdar a permissão de escrita do usuário app.
RUN useradd --create-home app && mkdir -p /app/dados_cargas && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/web/login', timeout=4)"

CMD ["uvicorn", "servidor.app:app", "--host", "0.0.0.0", "--port", "8000"]
