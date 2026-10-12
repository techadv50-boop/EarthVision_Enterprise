# File relay

A background service for the central VPS. It does not serve a website.

Every minute it logs into each drop folder over SFTP, compares that folder with the last snapshot, and copies only files that are new or changed. It then forwards those files to one destination, a chosen list, or every destination. A zip is one file. A new file inside an existing folder is new on its own.

Local copies live on the VPS for 24 hours (or `local_ttl_hours`) and are then deleted. The shared source and the destination servers keep their copies. Deleting a file on the source does not delete it from a destination.

Plain FTP is not used. SFTP is the connection. FTPS is available only when a shared account has no SFTP.

| Server | Protocol | Port |
| --- | --- | --- |
| Namecheap shared hosting | SFTP | 21098 |
| A VPS | SFTP | 22 |
| Shared host with SFTP turned off | FTPS | 21 |

The relay opens these connections outbound. Nothing from this service is installed on the shared servers.

## Configure

```bash
sudo mkdir -p /etc/file-relay/keys /var/lib/file-relay
sudo cp config.example.yaml /etc/file-relay/config.yaml
sudo cp deploy/relay.env.example /etc/file-relay/relay.env
```

Edit the host, port, user, directory, and `deliver_to` for each server. Put passwords in `/etc/file-relay/relay.env`:

```bash
SOURCE_PASSWORD=the-cpanel-password
```

A VPS destination should use an SSH key (`private_key_path`) instead of a password. `host_key_policy: reject` refuses an unknown server. `accept-new` stores the key the first time; use that only for a server you just pointed at.

`deliver_to` on a source is `all`, one destination id, or a list such as `[archive, shared-copy]`. Adding another shared host or VPS is another entry in `sources` or `destinations`.

A file is copied only after its size and modification time stay unchanged for `stability_seconds`, so a half-written upload waits for the next pass. A forward that fails is retried on the next pass and is not marked done.

## Run

From a checkout of this directory, with Python 3.11 or newer:

```bash
python3 -m venv /opt/file-relay/venv
/opt/file-relay/venv/bin/pip install .
sudo useradd --system --create-home --home-dir /var/lib/file-relay file-relay
sudo chown -R file-relay:file-relay /var/lib/file-relay
sudo cp deploy/relay.service /etc/systemd/system/file-relay.service
sudo systemctl enable --now file-relay
```

`ExecStart` in the unit file expects the virtualenv at `/opt/file-relay/venv` and the config at `/etc/file-relay/config.yaml`.

One pass, then exit:

```bash
python -m relay --config /etc/file-relay/config.yaml --once
```

Logs go to stdout (journald under systemd). The SQLite file at `database_path` records what was forwarded. The staging directory holds the short-lived copies.

## Docker

```bash
docker compose up -d --build
```

`compose.yaml` reads `/etc/file-relay/relay.env` and mounts `/etc/file-relay/config.yaml` plus `/etc/file-relay/keys`.
