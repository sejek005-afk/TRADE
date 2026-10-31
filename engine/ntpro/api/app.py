"""API موتور: FastAPI + WebSocket، فقط HTTPS، JWT + 2FA، محدودیت IP و نرخ."""
from __future__ import annotations

import asyncio
import json
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import __version__
from ..learning import fatigue, guard
from ..logs import RING
from ..security.auth import Auth, RateLimiter, ip_allowed
from ..sessions import to_tehran
from ..strategies import NAMES_FA


class SetupIn(BaseModel):
    setup_code: str
    username: str
    password: str


class ConfirmIn(BaseModel):
    username: str
    code: str


class LoginIn(BaseModel):
    username: str
    password: str
    code: str


class RefreshIn(BaseModel):
    refresh_token: str


class ToggleIn(BaseModel):
    enabled: bool


class KillIn(BaseModel):
    active: bool
    reason: str = ""


class MT5In(BaseModel):
    login: int = 0
    password: str = ""
    server: str = ""
    path: str = ""
    shared: bool = True          # استفاده از همان متاتریدرِ باز روی سرور (بدون رمز)


class ConfigIn(BaseModel):
    patch: dict
    reason: str = ""


class BacktestIn(BaseModel):
    days: int = 60
    symbols: list[str] | None = None
    per_strategy: bool = True
    use_ticks: bool = False


def _client_ip(request) -> str:
    return request.client.host if request.client else "?"


def create_app(engine) -> FastAPI:
    app = FastAPI(title="NeuroTrader Pro", version=__version__, docs_url=None, redoc_url=None)
    db, cfg = engine.db, engine.cfg
    auth = Auth(db, engine.vault.key, cfg)
    limiter = RateLimiter(int(cfg.get("api", "rate_limit_per_min")))
    app.state.auth = auth

    @app.middleware("http")
    async def guard_mw(request: Request, call_next):
        ip = _client_ip(request)
        if not ip_allowed(ip, cfg.get("api", "ip_allowlist") or []):
            return JSONResponse({"detail": "IP مجاز نیست"}, status_code=403)
        if not limiter.allow(ip):
            return JSONResponse({"detail": "تعداد درخواست بیش از حد مجاز"}, status_code=429)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    def user(request: Request) -> str:
        h = request.headers.get("authorization", "")
        tok = h[7:] if h.lower().startswith("bearer ") else ""
        u = auth.verify_access(tok)
        if not u:
            raise HTTPException(401, "نیاز به ورود")
        return u

    def audit(request: Request, u: str, action: str, result: str = "ok"):
        db.audit(u, _client_ip(request), action, result)

    # ---------- عمومی ----------
    @app.get("/api/ping")
    def ping():
        return {"ok": True, "version": __version__, "setup_required": not auth.has_users(), "time": int(time.time())}

    @app.post("/api/auth/setup")
    def setup(body: SetupIn, request: Request):
        ip = _client_ip(request)
        if limiter.is_locked(ip):
            raise HTTPException(429, "قفل موقت")
        try:
            out = auth.register(body.setup_code, body.username, body.password)
        except (PermissionError, ValueError) as e:
            limiter.fail(ip)
            raise HTTPException(400, str(e))
        db.audit(body.username, ip, "setup", "ok")
        return out

    @app.post("/api/auth/setup/confirm")
    def setup_confirm(body: ConfirmIn, request: Request):
        if not auth.confirm_totp(body.username, body.code):
            limiter.fail(_client_ip(request))
            raise HTTPException(400, "کد تأیید اشتباه است")
        return auth.issue(body.username)

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request):
        ip = _client_ip(request)
        if limiter.is_locked(ip):
            raise HTTPException(429, "به دلیل تلاش‌های ناموفق، ۱۵ دقیقه قفل است")
        tok = auth.login(body.username, body.password, body.code)
        if not tok:
            limiter.fail(ip)
            db.audit(body.username, ip, "login", "fail")
            raise HTTPException(401, "نام کاربری، رمز یا کد دومرحله‌ای اشتباه است")
        db.audit(body.username, ip, "login", "ok")
        return tok

    @app.post("/api/auth/refresh")
    def refresh(body: RefreshIn):
        tok = auth.refresh(body.refresh_token)
        if not tok:
            raise HTTPException(401, "نشست منقضی شده؛ دوباره وارد شوید")
        return tok

    @app.post("/api/auth/logout_all")
    def logout_all(request: Request, u: str = Depends(user)):
        auth.revoke_all(u)
        audit(request, u, "logout_all")
        return {"ok": True}

    # ---------- وضعیت ----------
    @app.get("/api/state")
    def state(u: str = Depends(user)):
        return engine.snapshot()

    @app.get("/api/trades")
    def trades(status: str = "closed", limit: int = 100, offset: int = 0, u: str = Depends(user)):
        rows = db.query("SELECT * FROM trades WHERE status=? ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT ? OFFSET ?",
                        (status, min(limit, 500), offset))
        for r in rows:
            r["strategies"] = json.loads(r["strategies"] or "[]")
            r["strategies_fa"] = [NAMES_FA.get(s, s) for s in r["strategies"]]
            r["entry_time_tehran"] = to_tehran(r["entry_time"]) if r["entry_time"] else ""
            r["exit_time_tehran"] = to_tehran(r["exit_time"]) if r["exit_time"] else ""
            r.pop("features", None)
        return rows

    @app.get("/api/signals")
    def signals(limit: int = 100, u: str = Depends(user)):
        rows = db.query("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (min(limit, 500),))
        for r in rows:
            r["strategies"] = json.loads(r["strategies"] or "[]")
            r["payload"] = json.loads(r["payload"] or "{}")
            r["time_tehran"] = to_tehran(r["time"])
        return rows

    # ---------- کنترل ----------
    @app.post("/api/bot")
    def bot(body: ToggleIn, request: Request, u: str = Depends(user)):
        cfg.update({"bot_enabled": body.enabled}, user=u, reason="روشن/خاموش از اپ")
        audit(request, u, f"bot {'on' if body.enabled else 'off'}")
        return {"ok": True, "bot_enabled": body.enabled}

    @app.post("/api/kill")
    def kill(body: KillIn, request: Request, u: str = Depends(user)):
        db.kv_set("kill_switch", {"active": body.active, "reason": body.reason or ("دستی" if body.active else ""),
                                  "time": int(time.time()), "by": u})
        if not body.active:
            db.kv_set("equity_peak", (engine.account_info or {}).get("equity"))
            db.kv_set("execution_halt", {"active": False})
        engine.notifier.send("critical" if body.active else "info", "kill_switch",
                             f"Kill Switch {'فعال' if body.active else 'غیرفعال'} شد توسط {u}")
        audit(request, u, f"kill {body.active}")
        return {"ok": True}

    @app.post("/api/positions/{trade_id}/close")
    def close_pos(trade_id: int, request: Request, u: str = Depends(user)):
        ok = engine.close_trade_manual(trade_id, u)
        audit(request, u, f"close {trade_id}", "ok" if ok else "fail")
        if not ok:
            raise HTTPException(400, "بستن انجام نشد")
        return {"ok": True}

    @app.get("/api/config")
    def get_config(u: str = Depends(user)):
        return {"config": cfg.public(), "strategies_fa": NAMES_FA}

    @app.put("/api/config")
    def put_config(body: ConfigIn, request: Request, u: str = Depends(user)):
        forbidden = {"api"} & set(body.patch)
        if forbidden:
            raise HTTPException(400, "تنظیمات API فقط از روی سرور قابل تغییر است")
        try:
            changes = cfg.update(body.patch, user=u, reason=body.reason or "تغییر از اپ")
        except ValueError as e:
            raise HTTPException(400, str(e))
        engine.clock.cfg = cfg.get("sessions")
        engine.pipeline.clock.cfg = cfg.get("sessions")
        audit(request, u, "config", "; ".join(changes)[:500])
        return {"ok": True, "changes": changes}

    @app.get("/api/config/versions")
    def config_versions(u: str = Depends(user)):
        rows = db.query("SELECT id,time,user,reason,changes FROM config_versions ORDER BY id DESC LIMIT 100")
        for r in rows:
            r["changes"] = json.loads(r["changes"] or "[]")
            r["time_tehran"] = to_tehran(r["time"])
        return rows

    @app.post("/api/config/versions/{vid}/restore")
    def config_restore(vid: int, request: Request, u: str = Depends(user)):
        row = db.one("SELECT snapshot FROM config_versions WHERE id=?", (vid,))
        if not row:
            raise HTTPException(404, "نسخه پیدا نشد")
        snap = json.loads(row["snapshot"])
        snap.pop("api", None)
        changes = cfg.update(snap, user=u, reason=f"بازگردانی نسخه‌ی #{vid}")
        audit(request, u, f"config restore {vid}")
        return {"ok": True, "changes": changes}

    @app.post("/api/mt5/credentials")
    def mt5_credentials(body: MT5In, request: Request, u: str = Depends(user)):
        if not body.shared and not body.password:
            raise HTTPException(400, "برای ترمینال جداگانه رمز لازم است")
        if body.password:
            engine.vault.store_secret("mt5", body.password)    # رمزنگاری‌شده روی سرور؛ هیچ‌وقت برگردانده نمی‌شود
        patch = {"mt5": {"login": body.login, "shared_terminal": body.shared, "path": body.path}}
        if body.server:
            patch["mt5"]["server"] = body.server
        cfg.update(patch, user=u, reason="به‌روزرسانی حساب MT5")
        try:
            engine.broker.shutdown()
        except Exception:
            pass
        engine.health["mt5"] = False
        engine._timers.pop("reconnect", None)
        audit(request, u, "mt5 credentials")
        return {"ok": True}

    # ---------- یادگیری ----------
    @app.get("/api/learning")
    def learning(u: str = Depends(user)):
        champ_id, champ = engine.registry.champion()
        chall_id, _ = engine.registry.challenger()
        return {
            "weights": engine.bandit.all_weights(),
            "log": db.query("SELECT * FROM weight_log ORDER BY id DESC LIMIT 200"),
            "snapshots": db.query("SELECT id,time,label,healthy FROM snapshots ORDER BY id DESC LIMIT 30"),
            "models": engine.registry.list(), "champion": champ_id, "challenger": chall_id,
            "challenger_since": db.kv_get("challenger_since"),
            "nn_active": bool(getattr(champ, "nn_active", False)) if champ else False,
            "paused": db.kv_get("learning_paused") or {"paused": False},
            "suspended": db.kv_get("suspended_strategies") or {},
            "training": engine.training, "strategies_fa": NAMES_FA,
            "recent_probs": db.query("SELECT time,symbol,direction,combined_score,ml_prob,nn_prob,shadow_prob,accepted "
                                     "FROM signals WHERE ml_prob IS NOT NULL OR shadow_prob IS NOT NULL ORDER BY id DESC LIMIT 50"),
        }

    @app.post("/api/learning/pause")
    def learning_pause(request: Request, u: str = Depends(user)):
        db.kv_set("learning_paused", {"paused": True, "reason": f"توقف دستی توسط {u}", "time": int(time.time())})
        audit(request, u, "learning pause")
        return {"ok": True}

    @app.post("/api/learning/resume")
    def learning_resume(request: Request, u: str = Depends(user)):
        guard.resume(db, u)
        audit(request, u, "learning resume")
        return {"ok": True}

    @app.post("/api/learning/rollback")
    def learning_rollback(request: Request, snapshot_id: int | None = None, u: str = Depends(user)):
        snap = engine.bandit.rollback(snapshot_id)
        if not snap:
            raise HTTPException(404, "نسخه‌ی سالمی برای برگشت وجود ندارد")
        audit(request, u, f"weights rollback {snap['id']}")
        return {"ok": True, "snapshot": snap["id"]}

    @app.post("/api/learning/model_rollback")
    def model_rollback(request: Request, model_id: int | None = None, u: str = Depends(user)):
        mid = engine.registry.rollback(model_id)
        engine.reload_models()
        audit(request, u, f"model rollback {mid}")
        if not mid:
            raise HTTPException(404, "مدل قبلی وجود ندارد")
        return {"ok": True, "model": mid}

    @app.post("/api/learning/train")
    def learning_train(request: Request, u: str = Depends(user)):
        threading.Thread(target=engine.run_training, daemon=True).start()
        audit(request, u, "train now")
        return {"ok": True}

    @app.post("/api/strategies/{name}/reinstate")
    def reinstate(name: str, request: Request, u: str = Depends(user)):
        fatigue.reinstate(db, name)
        audit(request, u, f"reinstate {name}")
        return {"ok": True}

    # ---------- اخبار ----------
    @app.get("/api/news")
    def news(limit: int = 100, u: str = Depends(user)):
        rows = db.query("SELECT * FROM news ORDER BY time DESC LIMIT ?", (min(limit, 300),))
        for r in rows:
            r["effects"] = json.loads(r["effects"] or "{}")
            r["time_tehran"] = to_tehran(r["time"])
        return rows

    @app.get("/api/calendar")
    def calendar(u: str = Depends(user)):
        now = time.time()
        evs = [e.__dict__ | {"time_tehran": to_tehran(e.time), "high": e.is_high}
               for e in sorted(engine.calendar.events, key=lambda e: e.time) if e.time > now - 86400]
        return {"source": engine.calendar.source, "events": evs[:300]}

    # ---------- سلامت، گزارش، لاگ ----------
    @app.get("/api/health")
    def health(u: str = Depends(user)):
        snap = engine.snapshot()["health"]
        snap["history"] = db.query("SELECT * FROM health ORDER BY time DESC LIMIT 120")
        snap["slippage"] = db.query("SELECT symbol, AVG(slippage_points) avg, MAX(slippage_points) max, COUNT(*) n "
                                    "FROM trades WHERE slippage_points IS NOT NULL GROUP BY symbol")
        return snap

    @app.get("/api/reports/weekly")
    def weekly(u: str = Depends(user)):
        from ..journal import weekly_report
        return db.kv_get("weekly_report") or weekly_report(db)

    @app.get("/api/journal")
    def journal_ep(limit: int = 50, u: str = Depends(user)):
        rows = db.query("SELECT id,symbol,direction,entry_time,exit_time,pnl,r_multiple,reason_open,reason_close,status "
                        "FROM trades ORDER BY entry_time DESC LIMIT ?", (min(limit, 300),))
        for r in rows:
            r["entry_time_tehran"] = to_tehran(r["entry_time"]) if r["entry_time"] else ""
            r["exit_time_tehran"] = to_tehran(r["exit_time"]) if r["exit_time"] else ""
        return rows

    @app.get("/api/logs")
    def logs(after: int = 0, u: str = Depends(user)):
        return RING.since(after)

    @app.get("/api/alerts")
    def alerts(after: int = 0, u: str = Depends(user)):
        rows = db.query("SELECT * FROM alerts WHERE id>? ORDER BY id DESC LIMIT 200", (after,))
        for r in rows:
            r["time_tehran"] = to_tehran(r["time"])
        return rows

    @app.get("/api/audit")
    def audit_log(u: str = Depends(user)):
        rows = db.query("SELECT * FROM audit ORDER BY id DESC LIMIT 200")
        for r in rows:
            r["time_tehran"] = to_tehran(r["time"])
        return rows

    # ---------- بک‌تست ----------
    @app.post("/api/backtest")
    def backtest(body: BacktestIn, request: Request, u: str = Depends(user)):
        if engine.backtest_state["running"]:
            raise HTTPException(409, "بک‌تست در حال اجراست")
        threading.Thread(target=engine.run_backtest, kwargs=body.model_dump(), daemon=True).start()
        audit(request, u, f"backtest {body.days}d")
        return {"ok": True}

    @app.get("/api/backtest")
    def backtest_result(u: str = Depends(user)):
        return {"running": engine.backtest_state["running"], "last": engine.backtest_state.get("last")}

    # ---------- WebSocket زنده ----------
    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        token = websocket.query_params.get("token", "")
        ip = websocket.client.host if websocket.client else "?"
        if not ip_allowed(ip, cfg.get("api", "ip_allowlist") or []) or not auth.verify_access(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        last_log = int(websocket.query_params.get("log_after", 0) or 0)
        last_alert = (db.one("SELECT MAX(id) m FROM alerts") or {}).get("m") or 0
        try:
            while True:
                if not auth.verify_access(token):
                    await websocket.close(code=4401)
                    return
                snap = await asyncio.to_thread(engine.snapshot)
                await websocket.send_text(json.dumps({"type": "state", "data": snap}, ensure_ascii=False, default=str))
                lines = RING.since(last_log, 100)
                if lines:
                    last_log = lines[-1]["id"]
                    await websocket.send_text(json.dumps({"type": "log", "data": lines}, ensure_ascii=False))
                new = db.query("SELECT * FROM alerts WHERE id>? ORDER BY id", (last_alert,))
                if new:
                    last_alert = new[-1]["id"]
                    await websocket.send_text(json.dumps({"type": "alerts", "data": new}, ensure_ascii=False))
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return
        except Exception:
            return

    return app
