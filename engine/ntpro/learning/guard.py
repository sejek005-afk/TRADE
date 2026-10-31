"""ترمز اضطراری یادگیری: اگر Drawdown از حد رد شد، یادگیری متوقف و به آخرین نسخه‌ی سالم برمی‌گردد.

یادگیری فقط بعد از تأیید دستی در اپ دوباره فعال می‌شود.
"""
from __future__ import annotations

import time


def check_brake(db, cfg, bandit, registry, dd_pct: float) -> bool:
    limit = float(cfg.get("learning", "drawdown_brake_pct"))
    state = db.kv_get("learning_paused", {}) or {}
    if dd_pct < limit or state.get("paused"):
        return False
    snap = bandit.rollback()
    model_id = None
    if snap:
        import json
        models = json.loads(snap.get("models") or "{}")
        model_id = models.get("champion")
        if model_id:
            registry.promote(int(model_id), "ترمز اضطراری: برگشت به مدل سالم")
    db.kv_set("learning_paused", {"paused": True, "reason": f"Drawdown {dd_pct:.1f}٪ ≥ {limit}٪",
                                  "time": int(time.time()), "rolled_back_to": snap["id"] if snap else None})
    db.alert("critical", "learning_brake",
             f"ترمز یادگیری: افت {dd_pct:.1f}٪. یادگیری متوقف شد و وزن‌ها/مدل به آخرین نسخه‌ی سالم برگشت. "
             "برای ادامه از اپ تأیید کنید.")
    return True


def resume(db, user: str) -> None:
    db.kv_set("learning_paused", {"paused": False, "resumed_by": user, "time": int(time.time())})
    db.alert("info", "learning", f"یادگیری توسط {user} دوباره فعال شد")
