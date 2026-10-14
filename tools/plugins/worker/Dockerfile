# Restricted SATEYE plugin worker (P2A) — NOT the Host Shell image.
# No DB credentials, no app secrets, no Docker socket.
FROM python:3.12-slim-bookworm

WORKDIR /work
COPY contract.py executor.py server.py /work/

# Non-root; no shell login needed
USER 65532:65532
ENV EV_ARTIFACTS_ROOT=/tool_packs/artifacts \
    EV_PLUGIN_WORKER_PORT=8091 \
    EV_PLUGIN_WORKER_HOST=0.0.0.0 \
    EV_PLUGIN_WORKER_TIMEOUT_SEC=5 \
    EV_PLUGIN_WORKER_READONLY=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL= \
    SECRET_KEY= \
    MASTER_PASSWORD= \
    ADMIN_PASSWORD= \
    DOCKER_HOST=

EXPOSE 8091
CMD ["python3", "/work/server.py"]
