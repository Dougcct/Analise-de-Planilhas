#!/bin/sh
# Restauração de um backup do banco (fase 7, DOCS/18 §7). Decifra, descomprime e aplica num banco.
# TESTE DE RESTAURAÇÃO: restaure para um banco DESCARTÁVEL (ex.: restore_teste), confira as contagens
# e descarte — nunca por cima do banco de produção. É o que valida que o backup presta.
#
# Uso:  BACKUP_PASSPHRASE=... [PGPASSWORD=...] sh restore.sh <arquivo.sql.gz.enc> [host] [banco] [usuario]
set -eu

ARQ="${1:?informe o arquivo .sql.gz.enc}"
HOST="${2:-db}"
DB="${3:-restore_teste}"
USER="${4:-analise}"
: "${BACKUP_PASSPHRASE:?defina BACKUP_PASSPHRASE}"

command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null 2>&1 || true

openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$ARQ" | gunzip | psql -h "$HOST" -U "$USER" -d "$DB"
echo "restaurado em $DB (host $HOST)."
