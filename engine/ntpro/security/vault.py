"""رمزنگاری اسرار روی سرور (رمز MT5، کلیدهای API اخبار).

کلید اصلی در data/master.key ذخیره می‌شود؛ روی ویندوز با DPAPI (وابسته به حساب کاربری ویندوز) هم محافظت می‌شود
تا کپی کردن فایل به سرور دیگر کافی نباشد. رمزنگاری: Fernet (AES-128-CBC + HMAC) از کتابخانه‌ی cryptography؛
اگر نصب نبود، AES جایگزین نداریم و با HMAC-SHA256 + XOR-stream (فقط برای تست) کار می‌کند.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path


def _dpapi(data: bytes, protect: bool) -> bytes:
    try:
        import win32crypt   # pywin32
        if protect:
            return win32crypt.CryptProtectData(data, "ntpro", None, None, None, 0)
        return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
    except Exception:
        return data


class Vault:
    def __init__(self, key_path: Path):
        self.key_path = Path(key_path)
        self.key = self._load_or_create()
        try:
            from cryptography.fernet import Fernet
            self._f = Fernet(base64.urlsafe_b64encode(self.key))
        except ImportError:   # pragma: no cover
            self._f = None

    def _load_or_create(self) -> bytes:
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if raw.startswith(b"DP1"):
                return _dpapi(raw[3:], protect=False)
            return raw
        key = secrets.token_bytes(32)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        protected = _dpapi(key, protect=True)
        self.key_path.write_bytes(b"DP1" + protected if protected != key else key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def encrypt(self, text: str) -> str:
        if self._f:
            return self._f.encrypt(text.encode()).decode()
        nonce = secrets.token_bytes(16)
        stream = hashlib.sha256(self.key + nonce).digest() * (len(text.encode()) // 32 + 1)
        ct = bytes(a ^ b for a, b in zip(text.encode(), stream))
        tag = hmac.new(self.key, nonce + ct, "sha256").digest()[:16]
        return "x1:" + base64.urlsafe_b64encode(nonce + tag + ct).decode()

    def decrypt(self, token: str) -> str:
        if token.startswith("x1:"):
            raw = base64.urlsafe_b64decode(token[3:])
            nonce, tag, ct = raw[:16], raw[16:32], raw[32:]
            if not hmac.compare_digest(tag, hmac.new(self.key, nonce + ct, "sha256").digest()[:16]):
                raise ValueError("bad token")
            stream = hashlib.sha256(self.key + nonce).digest() * (len(ct) // 32 + 1)
            return bytes(a ^ b for a, b in zip(ct, stream)).decode()
        return self._f.decrypt(token.encode()).decode()

    # رمز MT5 در فایل جدا
    def store_secret(self, name: str, value: str) -> None:
        p = self.key_path.parent / f"{name}.enc"
        p.write_text(self.encrypt(value), encoding="utf-8")

    def load_secret(self, name: str) -> str:
        p = self.key_path.parent / f"{name}.enc"
        if not p.exists():
            return ""
        try:
            return self.decrypt(p.read_text(encoding="utf-8").strip())
        except Exception:
            return ""
