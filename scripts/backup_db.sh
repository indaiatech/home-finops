#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups"
mkdir -p "${BACKUP_DIR}"

# Load non-empty DB vars from .env if present
if [[ -f "${ROOT_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "${ROOT_DIR}/.env" && set +a
fi

DB_USER="${POSTGRES_USER:-finops}"
DB_NAME="${POSTGRES_DB:-finops}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="${BACKUP_DIR}/finops-${TS}.sql.gz"

docker compose exec -T postgres pg_dump -U "${DB_USER}" "${DB_NAME}" | gzip > "${OUT_FILE}"
echo "Backup written to ${OUT_FILE} (gitignored)."
