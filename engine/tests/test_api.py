import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from ntpro.broker.paper import PaperBroker  # noqa: E402
from ntpro.engine import Engine  # noqa: E402
from ntpro.security.auth import totp  # noqa: E402


def test_api_auth_and_endpoints(tmp_path):
    broker = PaperBroker(None)
    eng = Engine(tmp_path / "d", broker=broker)
    broker.cfg = eng.cfg
    from ntpro.api.app import create_app
    app = create_app(eng)
    c = TestClient(app)
    assert c.get("/api/ping").json()["setup_required"]
    assert c.get("/api/state").status_code == 401
    code = app.state.auth.setup_code(tmp_path)
    r = c.post("/api/auth/setup", json={"setup_code": code, "username": "u", "password": "longpassword1"})
    secret = r.json()["secret"]
    tok = c.post("/api/auth/setup/confirm", json={"username": "u", "code": totp(secret)}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert c.get("/api/state", headers=h).status_code == 200
    assert c.post("/api/bot", json={"enabled": True}, headers=h).json()["bot_enabled"]
    r = c.put("/api/config", json={"patch": {"risk": {"risk_per_trade_pct": 0.7}}}, headers=h)
    assert r.status_code == 200 and r.json()["changes"]
    assert c.put("/api/config", json={"patch": {"api": {"port": 1}}}, headers=h).status_code == 400
    assert c.put("/api/config", json={"patch": {"risk": {"risk_per_trade_pct": 9}}}, headers=h).status_code == 400
    assert c.get("/api/config/versions", headers=h).json()
    assert c.post("/api/mt5/credentials", json={"login": 1, "password": "pw", "server": "s"}, headers=h).json()["ok"]
    assert eng.vault.load_secret("mt5") == "pw"
    assert "pw" not in str(c.get("/api/config", headers=h).json())
    for ep in ("/api/learning", "/api/news", "/api/calendar", "/api/health", "/api/journal", "/api/logs",
               "/api/alerts", "/api/trades", "/api/signals", "/api/reports/weekly", "/api/backtest"):
        assert c.get(ep, headers=h).status_code == 200, ep
    assert c.post("/api/kill", json={"active": True, "reason": "test"}, headers=h).json()["ok"]
    assert eng.db.kv_get("kill_switch")["active"]
    bad = c.post("/api/auth/login", json={"username": "u", "password": "x", "code": "1"})
    assert bad.status_code == 401
    with c.websocket_connect(f"/ws?token={tok['access_token']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state"
