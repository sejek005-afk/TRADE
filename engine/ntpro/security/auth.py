"""احراز هویت: رمز (PBKDF2) + ورود دومرحله‌ای TOTP (Google Authenticator) + JWT (HS256) + محدودیت نرخ و IP."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import struct
import threading
import time
from collections import defaultdict, deque

PBKDF2_ITER = 240_000
DEVICE_DAYS = 3650          # گوشیِ جفت‌شده تا ۱۰ سال بدون ورود دوباره وصل می‌ماند


# ---------- رمز ----------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITER)
    return f"pbkdf2${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


# ---------- TOTP (RFC 6238) ----------
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, t: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((t if t is not None else time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip()
    now = time.time()
    return any(hmac.compare_digest(totp(secret, now + k * 30), code) for k in range(-window, window + 1))


def totp_uri(secret: str, username: str, issuer: str = "NeuroTraderPro") -> str:
    return f"otpauth://totp/{issuer}:{username}?secret={secret}&issuer={issuer}&digits=6&period=30"


# ---------- JWT ----------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwt_encode(payload: dict, key: bytes) -> str:
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(key, f"{head}.{body}".encode(), "sha256").digest())
    return f"{head}.{body}.{sig}"


def jwt_decode(token: str, key: bytes) -> dict | None:
    try:
        head, body, sig = token.split(".")
        exp_sig = _b64(hmac.new(key, f"{head}.{body}".encode(), "sha256").digest())
        if not hmac.compare_digest(sig, exp_sig):
            return None
        if json.loads(_unb64(head)).get("alg") != "HS256":
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ---------- محدودیت نرخ / قفل ----------
class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.fails: dict[str, deque] = defaultdict(deque)
        self.locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            if self.locked.get(key, 0) > now:
                return False
            q = self.hits[key]
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True

    def fail(self, key: str, max_fails: int = 5, lock_seconds: int = 900) -> None:
        now = time.time()
        with self._lock:
            q = self.fails[key]
            while q and q[0] < now - 900:
                q.popleft()
            q.append(now)
            if len(q) >= max_fails:
                self.locked[key] = now + lock_seconds

    def is_locked(self, key: str) -> bool:
        return self.locked.get(key, 0) > time.time()


def ip_allowed(ip: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(n, strict=False) for n in allowlist)


class Auth:
    def __init__(self, db, key: bytes, cfg):
        self.db, self.key, self.cfg = db, key, cfg

    def has_users(self) -> bool:
        return bool(self.db.one("SELECT 1 FROM users WHERE totp_confirmed=1"))

    def setup_code(self, data_dir) -> str:
        code = self.db.kv_get("setup_code")
        if not code:
            code = secrets.token_hex(4).upper()
            self.db.kv_set("setup_code", code)
        (data_dir / "SETUP_CODE.txt").write_text(code, encoding="utf-8")
        return code

    def register(self, setup_code: str, username: str, password: str) -> dict:
        if self.has_users():
            raise PermissionError("کاربر از قبل ساخته شده است")
        if not hmac.compare_digest(str(self.db.kv_get("setup_code", "")), (setup_code or "").strip().upper()):
            raise PermissionError("کد راه‌اندازی اشتباه است")
        if len(password) < 10:
            raise ValueError("رمز باید حداقل ۱۰ کاراکتر باشد")
        secret = new_totp_secret()
        self.db.execute("INSERT OR REPLACE INTO users(username,pw_hash,totp_secret,totp_confirmed,created) VALUES(?,?,?,?,?)",
                        (username, hash_password(password), secret, 0, int(time.time())))
        return {"secret": secret, "uri": totp_uri(secret, username)}

    def confirm_totp(self, username: str, code: str) -> bool:
        u = self.db.one("SELECT * FROM users WHERE username=?", (username,))
        if not u or not verify_totp(u["totp_secret"], code):
            return False
        self.db.execute("UPDATE users SET totp_confirmed=1 WHERE username=?", (username,))
        self.db.kv_set("setup_code", "")
        return True

    def pair(self, setup_code: str) -> dict:
        """جفت کردن گوشی فقط با کد اتصال (بدون رمز و بدون Google Authenticator).
        گوشی یک توکن بلندمدت می‌گیرد و از آن به بعد مستقیم وارد می‌شود."""
        stored = str(self.db.kv_get("setup_code", "") or "")
        if not stored or not hmac.compare_digest(stored, (setup_code or "").strip().upper()):
            raise PermissionError("کد اتصال اشتباه است")
        u = self.db.one("SELECT username FROM users WHERE totp_confirmed=1 ORDER BY created LIMIT 1")
        username = u["username"] if u else "admin"
        if not u:
            self.db.execute("INSERT OR REPLACE INTO users(username,pw_hash,totp_secret,totp_confirmed,created) VALUES(?,?,?,?,?)",
                            (username, "", "", 1, int(time.time())))
        return self.issue(username, device=True)

    def login(self, username: str, password: str, code: str) -> dict | None:
        u = self.db.one("SELECT * FROM users WHERE username=? AND totp_confirmed=1", (username,))
        if not u or not verify_password(password, u["pw_hash"]) or not verify_totp(u["totp_secret"], code):
            return None
        return self.issue(username)

    def _access(self, username: str) -> dict:
        minutes = int(self.cfg.get("api")["access_token_minutes"])
        tok = jwt_encode({"sub": username, "typ": "access", "exp": int(time.time()) + minutes * 60}, self.key)
        return {"access_token": tok, "expires_in": minutes * 60}

    def issue(self, username: str, device: bool = False) -> dict:
        now = int(time.time())
        jti = secrets.token_hex(16)
        days = DEVICE_DAYS if device else int(self.cfg.get("api")["refresh_token_days"])
        refresh_exp = now + days * 86400
        self.db.execute("INSERT INTO refresh_tokens(jti,username,expires) VALUES(?,?,?)", (jti, username, refresh_exp))
        payload = {"sub": username, "typ": "refresh", "jti": jti, "exp": refresh_exp}
        if device:
            payload["dev"] = 1
        return {**self._access(username), "refresh_token": jwt_encode(payload, self.key)}

    def refresh(self, token: str) -> dict | None:
        p = jwt_decode(token, self.key)
        if not p or p.get("typ") != "refresh":
            return None
        row = self.db.one("SELECT * FROM refresh_tokens WHERE jti=? AND revoked=0", (p["jti"],))
        if p.get("dev"):
            # توکن گوشیِ جفت‌شده عوض نمی‌شود تا قطعی اینترنت هیچ‌وقت باعث بیرون افتادن نشود
            return {**self._access(p["sub"]), "refresh_token": token} if row else None
        if not row:
            # استفاده‌ی دوباره از توکن باطل‌شده = احتمال سرقت → همه باطل
            self.db.execute("UPDATE refresh_tokens SET revoked=1 WHERE username=?", (p["sub"],))
            return None
        self.db.execute("UPDATE refresh_tokens SET revoked=1 WHERE jti=?", (p["jti"],))   # یک‌بارمصرف
        return self.issue(p["sub"])

    def verify_access(self, token: str) -> str | None:
        p = jwt_decode(token, self.key)
        return p["sub"] if p and p.get("typ") == "access" else None

    def revoke_all(self, username: str) -> None:
        self.db.execute("UPDATE refresh_tokens SET revoked=1 WHERE username=?", (username,))
