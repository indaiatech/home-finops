#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="${ROOT_DIR}/local"
EXAMPLES_DIR="${ROOT_DIR}/config/examples"

mkdir -p "${LOCAL_DIR}/imports/person_a" "${LOCAL_DIR}/imports/person_b"

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
  echo "Created .env from .env.example (remember to populate real secrets)."
else
  echo "Skipping .env (already exists)."
fi

for file in people.yaml sources.yaml categories.yaml rules.yaml projections.yaml; do
  if [[ ! -f "${LOCAL_DIR}/${file}" ]]; then
    cp "${EXAMPLES_DIR}/${file}" "${LOCAL_DIR}/${file}"
    echo "Created local/${file} from config/examples/${file}"
  else
    echo "Skipping local/${file} (already exists)."
  fi
done

echo "Local initialization complete. Both .env and local/ are gitignored."
