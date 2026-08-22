#!/usr/bin/env bash
# Container entrypoint: applies pending Alembic migrations, then starts the
# FastAPI/Uvicorn server.
#
# This file is referenced by the Dockerfile (`RUN chmod +x entrypoint.sh` /
# `ENTRYPOINT ["./entrypoint.sh"]`) but was never actually included anywhere
# in the original project -- the Docker build would fail at the `chmod` step
# with "No such file or directory" without it.
#
# Deliberately does NOT run ingest.py here: re-running the ingestion pipeline
# on every container start/restart would re-embed the same knowledge_source
# files and pile up duplicate vectors in chroma_db each time (ingest.py's
# Chroma.from_documents(...) call appends rather than replacing the
# collection). Ingestion stays the explicit, manual step the README already
# documents ("python ingest.py") -- run it once after populating
# knowledge_source/, or wire it into a separate one-off job/step if you want
# it automated.
set -euo pipefail

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] Starting Uvicorn..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
