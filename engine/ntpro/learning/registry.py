"""رجیستری مدل‌ها: Champion/Challenger، حالت Shadow، نگه‌داری همه‌ی نسخه‌ها و Rollback فوری."""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

CHAMPION, CHALLENGER, RETIRED = "champion", "challenger", "retired"


class ModelRegistry:
    def __init__(self, db, model_dir: Path):
        self.db = db
        self.dir = Path(model_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[int, object] = {}

    def save(self, ensemble, metrics: dict, status: str = CHALLENGER, name: str = "ensemble") -> int:
        ver = (self.db.one("SELECT MAX(version) v FROM models WHERE name=?", (name,)) or {}).get("v") or 0
        ver += 1
        path = self.dir / f"{name}_v{ver}.pkl"
        with open(path, "wb") as fh:
            pickle.dump(ensemble, fh)
        if status == CHAMPION:
            self.db.execute("UPDATE models SET status=? WHERE status=? AND name=?", (RETIRED, CHAMPION, name))
        elif status == CHALLENGER:
            self.db.execute("UPDATE models SET status=? WHERE status=? AND name=?", (RETIRED, CHALLENGER, name))
        return self.db.execute("INSERT INTO models(name,version,path,created,metrics,status) VALUES(?,?,?,?,?,?)",
                               (name, ver, str(path), int(time.time()), json.dumps(metrics), status)).lastrowid

    def load(self, model_id: int):
        if model_id in self._cache:
            return self._cache[model_id]
        row = self.db.one("SELECT path FROM models WHERE id=?", (model_id,))
        if not row or not Path(row["path"]).exists():
            return None
        with open(row["path"], "rb") as fh:
            obj = pickle.load(fh)   # فایل‌ها فقط توسط خود موتور ساخته می‌شوند
        self._cache[model_id] = obj
        return obj

    def get(self, status: str, name: str = "ensemble"):
        row = self.db.one("SELECT id FROM models WHERE status=? AND name=? ORDER BY id DESC LIMIT 1", (status, name))
        return (row["id"], self.load(row["id"])) if row else (None, None)

    def champion(self):
        return self.get(CHAMPION)

    def challenger(self):
        return self.get(CHALLENGER)

    def promote(self, model_id: int, reason: str) -> None:
        self.db.execute("UPDATE models SET status=? WHERE status=?", (RETIRED, CHAMPION))
        self.db.execute("UPDATE models SET status=? WHERE id=?", (CHAMPION, model_id))
        self.db.alert("info", "model", f"مدل #{model_id} جایگزین شد: {reason}")

    def reject_challenger(self, reason: str) -> None:
        cid, _ = self.challenger()
        if cid:
            self.db.execute("UPDATE models SET status=? WHERE id=?", (RETIRED, cid))
            self.db.alert("info", "model", f"مدل چالشگر #{cid} رد شد: {reason}")

    def rollback(self, model_id: int | None = None) -> int | None:
        """برگشت به مدل قبلی (یا مدل مشخص)."""
        cur, _ = self.champion()
        if model_id is None:
            q = "SELECT id FROM models WHERE status=? AND id<? ORDER BY id DESC LIMIT 1"
            row = self.db.one(q, (RETIRED, cur or 10 ** 9))
            model_id = row["id"] if row else None
        if model_id is None:
            return None
        self.promote(model_id, "Rollback")
        return model_id

    def list(self) -> list[dict]:
        rows = self.db.query("SELECT id,name,version,created,metrics,status FROM models ORDER BY id DESC LIMIT 30")
        for r in rows:
            r["metrics"] = json.loads(r["metrics"] or "{}")
        return rows
