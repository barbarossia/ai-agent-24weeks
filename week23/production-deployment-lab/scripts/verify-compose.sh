#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
./scripts/init-local.sh

if [ -x .venv/bin/python ]; then
    LAB_PYTHON=.venv/bin/python
else
    LAB_PYTHON=python3
fi

docker compose up --build --detach --wait
"$LAB_PYTHON" -m week23_production_lab.eval --verify-observability
docker compose logs --no-color api > .local/api-logs.txt
"$LAB_PYTHON" -m week23_production_lab.eval \
    --verify-state-file .local/eval-state.json \
    --verify-log-file .local/api-logs.txt

docker compose restart api
"$LAB_PYTHON" -m week23_production_lab.eval --verify-state-file .local/eval-state.json

# `down` intentionally keeps the named postgres_data volume.
docker compose down
docker compose up --build --detach --wait
"$LAB_PYTHON" -m week23_production_lab.eval --verify-state-file .local/eval-state.json
"$LAB_PYTHON" -m week23_production_lab.eval --verify-observability

printf 'Compose smoke/eval passed. The stack is running; inspect it or run docker compose down -v to remove its database volume.\n'
