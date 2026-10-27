#!/bin/sh
# Backup CRIPTOGRAFADO do servidor v2 (fase 7, DOCS/18 §7): dump do banco + volume de cargas,
# cifrados com AES-256 (senha em BACKUP_PASSPHRASE, fora do git). Pensado para rodar num
# postgres:16-alpine (tem pg_dump); openssl é instalado se faltar.
#
# Uso:  BACKUP_PASSPHRASE=... [PGPASSWORD=...] sh backup.sh [host] [banco] [usuario]
# Cron (produção): diário, com cópia para FORA do servidor e teste de restauração periódico
#                  (backup nunca restaurado não conta como backup — ver restore.sh).
set -eu

HOST="${1:-db}"
DB="${2:-analise}"
USER="${3:-analise}"
DEST="${BACKUP_DIR:-/backups}"
: "${BACKUP_PASSPHRASE:?defina BACKUP_PASSPHRASE (a senha do backup, fora do git)}"

command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null 2>&1 || true

mkdir -p "$DEST"
TS="$(date +%Y%m%d-%H%M%S)"

cifrar() {   # stdin -> arquivo cifrado
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$1"
}

# 1) banco (dump SQL comprimido, depois cifrado)
ARQ_DB="$DEST/db-${DB}-${TS}.sql.gz.enc"
pg_dump -h "$HOST" -U "$USER" -d "$DB" | gzip | cifrar "$ARQ_DB"
echo "banco:  $ARQ_DB ($(wc -c < "$ARQ_DB") bytes)"

# 2) cargas (planilhas brutas enviadas), se o volume estiver montado
if [ -d "${CARGAS_DIR:-/cargas}" ]; then
    ARQ_CG="$DEST/cargas-${TS}.tar.gz.enc"
    tar -C "${CARGAS_DIR:-/cargas}" -czf - . | cifrar "$ARQ_CG"
    echo "cargas: $ARQ_CG ($(wc -c < "$ARQ_CG") bytes)"
fi

echo "OK — guarde uma cópia FORA do servidor e teste a restauração (restore.sh)."
