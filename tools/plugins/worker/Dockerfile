# Restricted SATEYE plugin worker (P2A.1) — NOT the Host Shell image.
FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir 'cryptography>=42,<46'

WORKDIR /work
COPY contract.py auth.py signatures.py registry_gate.py executor_core.py executor.py child_runner.py server.py /work/

USER 65532:65532
ENV EV_ARTIFACTS_ROOT=/tool_packs/artifacts \
    EV_TOOL_PACKS_ROOT=/tool_packs \
    EV_PLUGIN_REGISTRY=/tool_packs/plugin_registry.json \
    EV_PACK_PUBLISHERS=/tool_packs/publishers/approved_publishers.json \
    EV_PACK_TRUST_PROFILE=preview \
    EV_PACK_REQUIRE_SIGNATURE=1 \
    EV_PLUGIN_WORKER_PORT=8091 \
    EV_PLUGIN_WORKER_HOST=0.0.0.0 \
    EV_PLUGIN_WORKER_TIMEOUT_SEC=5 \
    EV_PLUGIN_WORKER_READONLY=1 \
    EV_PLUGIN_WORKER_NETWORK_POLICY=compose_internal \
    EV_PLUGIN_CHILD_AS_BYTES=268435456 \
    EV_PLUGIN_CHILD_CPU_SEC=5 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL= \
    SECRET_KEY= \
    MASTER_PASSWORD= \
    ADMIN_PASSWORD= \
    DOCKER_HOST=

EXPOSE 8091
CMD ["python3", "/work/server.py"]
