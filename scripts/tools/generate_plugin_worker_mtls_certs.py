#!/usr/bin/env python3
"""Generate preview/dev mTLS materials for Host Shell ↔ plugin worker.

Writes a local CA, worker server cert, and Host client cert under
``tools/plugins/worker/certs/`` (gitignored). Does NOT embed production secrets.

Usage:
  python3 scripts/tools/generate_plugin_worker_mtls_certs.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools" / "plugins" / "worker" / "certs"


def main() -> int:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("ERROR: cryptography package required", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    # CA
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SATEYE Plugin Worker Preview CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    def issue(cn: str, key, san_dns: list[str] | None = None):
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=365))
        )
        if san_dns:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName(d) for d in san_dns]),
                critical=False,
            )
        return builder.sign(ca_key, hashes.SHA256())

    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_cert = issue("plugin_worker", srv_key, san_dns=["plugin_worker", "localhost"])
    cli_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cli_cert = issue("host_shell", cli_key)

    def write_key(path: Path, key) -> None:
        path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        path.chmod(0o600)

    def write_cert(path: Path, cert) -> None:
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    write_key(OUT / "ca.key", ca_key)
    write_cert(OUT / "ca.crt", ca_cert)
    write_key(OUT / "server.key", srv_key)
    write_cert(OUT / "server.crt", srv_cert)
    write_key(OUT / "client.key", cli_key)
    write_cert(OUT / "client.crt", cli_cert)
    (OUT / "README.md").write_text(
        "# Preview mTLS materials\n\nGenerated locally. Do not commit private keys.\n"
        "Set EV_PLUGIN_WORKER_TLS=1 and point cert env vars at these files.\n",
        encoding="utf-8",
    )
    print(f"Wrote mTLS materials under {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
