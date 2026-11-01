import time

from ntpro.config import Config
from ntpro.db import DB
from ntpro.security.auth import (Auth, RateLimiter, hash_password, ip_allowed, jwt_decode, jwt_encode, totp,
                                 verify_password, verify_totp)
from ntpro.security.vault import Vault


def test_password_and_totp():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    secret = "JBSWY3DPEHPK3PXP"
    assert verify_totp(secret, totp(secret))
    assert not verify_totp(secret, "000000") or totp(secret) == "000000"
    # بردار تست RFC 6238 (SHA1، کلید 12345678901234567890، t=59 → 94287082 → ۶ رقم آخر)
    import base64
    s = base64.b32encode(b"12345678901234567890").decode()
    assert totp(s, 59, digits=8) == "94287082"


def test_jwt():
    k = b"k" * 32
    t = jwt_encode({"sub": "a", "typ": "access", "exp": time.time() + 60}, k)
    assert jwt_decode(t, k)["sub"] == "a"
    assert jwt_decode(t, b"x" * 32) is None
    assert jwt_decode(jwt_encode({"sub": "a", "exp": time.time() - 1}, k), k) is None
    assert jwt_decode(t[:-2] + "AA", k) is None


def test_vault_roundtrip(tmp_path):
    v = Vault(tmp_path / "master.key")
    tok = v.encrypt("s3cret-pass")
    assert "s3cret" not in tok
    assert Vault(tmp_path / "master.key").decrypt(tok) == "s3cret-pass"
    v.store_secret("mt5", "pw")
    assert v.load_secret("mt5") == "pw"
    assert "pw" not in (tmp_path / "mt5.enc").read_text()


def test_config_secrets_encrypted(tmp_path):
    v = Vault(tmp_path / "master.key")
    c = Config(tmp_path / "config.json", vault=v)
    c.update({"news": {"finnhub_key": "ABC123"}})
    raw = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert "ABC123" not in raw
    assert Config(tmp_path / "config.json", vault=v).get("news", "finnhub_key") == "ABC123"
    assert c.public()["news"]["finnhub_key"] == "••••••"


def test_auth_flow(tmp_path):
    db = DB(tmp_path / "t.db")
    cfg = Config(tmp_path / "c.json")
    a = Auth(db, b"k" * 32, cfg)
    code = a.setup_code(tmp_path)
    out = a.register(code, "admin", "verylongpassword")
    assert not a.has_users()
    assert a.confirm_totp("admin", totp(out["secret"]))
    assert a.has_users()
    assert a.login("admin", "verylongpassword", "123") is None or totp(out["secret"]) == "123"
    tok = a.login("admin", "verylongpassword", totp(out["secret"]))
    assert a.verify_access(tok["access_token"]) == "admin"
    new = a.refresh(tok["refresh_token"])
    assert new and a.refresh(tok["refresh_token"]) is None      # یک‌بارمصرف
    assert a.refresh(new["refresh_token"]) is None               # استفاده‌ی مجدد → همه باطل


def test_rate_limit_and_ip():
    r = RateLimiter(3)
    assert all(r.allow("1.1.1.1") for _ in range(3))
    assert not r.allow("1.1.1.1")
    for _ in range(5):
        r.fail("2.2.2.2")
    assert r.is_locked("2.2.2.2")
    assert ip_allowed("5.1.2.3", ["5.0.0.0/8"])
    assert not ip_allowed("6.1.2.3", ["5.0.0.0/8"])
    assert ip_allowed("6.1.2.3", [])


def test_config_guards(tmp_path):
    import pytest
    c = Config(tmp_path / "c.json")
    with pytest.raises(ValueError):
        c.update({"api": {"port": 8765}})        # پورت برنامه‌ی دیگر
    with pytest.raises(ValueError):
        c.update({"learning": {"max_step": 0.2}})
    with pytest.raises(ValueError):
        c.update({"mode": "live"})
    with pytest.raises(ValueError):
        c.update({"risk": {"risk_per_trade_pct": 5}})


def test_device_pairing(tmp_path):
    db = DB(tmp_path / "t.db")
    a = Auth(db, b"k" * 32, Config(tmp_path / "c.json"))
    code = a.setup_code(tmp_path)
    try:
        a.pair("WRONG")
        assert False
    except PermissionError:
        pass
    tok = a.pair(code.lower())
    assert a.has_users() and a.verify_access(tok["access_token"]) == "admin"
    assert jwt_decode(tok["refresh_token"], b"k" * 32)["exp"] > time.time() + 3000 * 86400
    # توکن گوشی عوض نمی‌شود و چند بار پشت سر هم قابل استفاده است
    for _ in range(3):
        r = a.refresh(tok["refresh_token"])
        assert r and r["refresh_token"] == tok["refresh_token"] and a.verify_access(r["access_token"]) == "admin"
    assert a.login("admin", "", "") is None                       # ورود با رمز خالی ممکن نیست
    assert a.pair(code)                                           # گوشی دوم / نصب دوباره با همان کد
    a.revoke_all("admin")
    assert a.refresh(tok["refresh_token"]) is None
