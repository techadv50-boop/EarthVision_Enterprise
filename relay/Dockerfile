FROM python:3.13-slim

WORKDIR /opt/file-relay

RUN useradd --system --create-home --home-dir /var/lib/file-relay file-relay

COPY pyproject.toml README.md requirements.txt config.example.yaml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && mkdir -p /etc/file-relay \
    && cp config.example.yaml /etc/file-relay/config.example.yaml

USER file-relay
WORKDIR /var/lib/file-relay

VOLUME ["/var/lib/file-relay", "/etc/file-relay"]

CMD ["python", "-m", "relay", "--config", "/etc/file-relay/config.yaml"]
