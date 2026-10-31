"""گواهی TLS خودامضا برای HTTPS (اپ اثر انگشت آن را Pin می‌کند)."""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
from pathlib import Path


def ensure_cert(data_dir: Path, hosts: list[str] | None = None) -> tuple[Path, Path, str]:
    cert, key = data_dir / "tls_cert.pem", data_dir / "tls_key.pem"
    if not (cert.exists() and key.exists()):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NeuroTraderPro")])
        alt = [x509.DNSName("localhost")]
        for h in hosts or []:
            try:
                alt.append(x509.IPAddress(ipaddress.ip_address(h)))
            except ValueError:
                alt.append(x509.DNSName(h))
        now = dt.datetime.now(dt.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
             .not_valid_after(now + dt.timedelta(days=3650))
             .add_extension(x509.SubjectAlternativeName(alt), critical=False)
             .sign(k, hashes.SHA256()))
        key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
        cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key, fingerprint(cert)


def fingerprint(cert_path: Path) -> str:
    """SHA-256 کلید عمومی (SPKI) — همان چیزی که اپ Pin می‌کند."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    c = x509.load_pem_x509_certificate(cert_path.read_bytes())
    spki = c.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    import base64
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()
