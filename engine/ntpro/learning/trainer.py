"""لایه‌ی ۳ یادگیری (هفتگی، آخر هفته که بازار تعطیل است):
ساخت دیتاست از داده‌ی تاریخی → Walk-Forward → مدل چالشگر در حالت Shadow → Champion/Challenger.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import frame
from ..pipeline import AccountState, Pipeline
from ..risk import RiskManager
from . import features as feats
from .models import Ensemble, GBMModel, SeqNet, auc, logloss

log = logging.getLogger("ntpro.trainer")


class _Capture:
    """مدل ساختگی که فقط ویژگی‌ها را جمع می‌کند (برای ساخت دیتاست با همان Pipeline موتور)."""

    def __init__(self):
        self.last = None

    def predict_one(self, tab, seq):
        self.last = (tab, seq)
        return 0.5, None


@dataclass
class Dataset:
    X: np.ndarray
    seq: np.ndarray
    y: np.ndarray
    rr: np.ndarray
    times: np.ndarray
    columns: list[str]


def build_dataset(cfg, symbol: str, candles: pd.DataFrame, spec, step: int = 1, warmup: int = 300) -> Dataset | None:
    f = frame.compute(candles)
    cap = _Capture()
    pipe = Pipeline(cfg, RiskManager(cfg), models=cap)
    horizon = int(cfg.get("exits", "time_stop_bars")) * 2
    min_rr = float(cfg.get("risk", "min_rr_after_costs"))
    rows, seqs, ys, rrs, ts = [], [], [], [], []
    acct = AccountState(10000, 10000)
    for i in range(warmup, len(candles) - horizon - 1, step):
        now = (candles.index[i] + pd.Timedelta(minutes=5)).to_pydatetime()
        cap.last = None
        ev = pipe.evaluate(symbol, candles.iloc[: i + 1], f.iloc[: i + 1], now,
                           spread_points=float(candles["spread"].iloc[i] or 0), spec=spec, account=acct,
                           ts=now.timestamp(), skip_risk=True)
        if cap.last is None or ev.decision is None:
            continue
        a = float(f["atr"].iloc[i])
        d = ev.decision.direction
        price = float(candles["close"].iloc[i])
        sl_dist = min(max(abs(price - ev.decision.sl), 0.8 * a), 3.0 * a)
        tp_dist = abs(ev.plan.tp - ev.plan.entry) if ev.plan else min_rr * sl_dist * 1.2
        y = feats.triple_barrier(candles, i, d, sl_dist, tp_dist, horizon)
        if y is None:
            continue
        tab, seq = cap.last
        rows.append(tab)
        seqs.append(seq)
        ys.append(y)
        rrs.append(tp_dist / sl_dist)
        ts.append(candles.index[i].value)
    if len(rows) < 200:
        return None
    X, cols = feats.to_matrix(rows)
    return Dataset(X, np.stack(seqs), np.array(ys, dtype=np.float32), np.array(rrs), np.array(ts), cols)


def merge(datasets: list[Dataset]) -> Dataset:
    cols = sorted(set().union(*[d.columns for d in datasets]))
    Xs = []
    for d in datasets:
        idx = {c: i for i, c in enumerate(d.columns)}
        Xs.append(np.stack([d.X[:, idx[c]] if c in idx else np.zeros(len(d.X)) for c in cols], axis=1))
    order = np.argsort(np.concatenate([d.times for d in datasets]))
    cat = lambda k: np.concatenate([getattr(d, k) for d in datasets])[order]  # noqa: E731
    return Dataset(np.concatenate(Xs)[order], cat("seq"), cat("y"), cat("rr"), cat("times"), cols)


def policy_stats(r: np.ndarray) -> dict:
    """PF، Expectancy و Drawdown (بر حسب R) برای یک دنباله‌ی نتایج."""
    if len(r) == 0:
        return {"n": 0, "pf": 0.0, "exp": 0.0, "dd": 0.0}
    gw, gl = r[r > 0].sum(), -r[r <= 0].sum()
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    return {"n": int(len(r)), "pf": float(gw / gl) if gl > 0 else float(gw > 0) * 99, "exp": float(r.mean()), "dd": dd}


def outcomes_r(y: np.ndarray, rr: np.ndarray) -> np.ndarray:
    return np.where(y == 1, rr, -1.0)


def walk_forward(ds: Dataset, folds: int = 4, threads: int = 2, nn_enabled: bool = True,
                 threshold: float = 0.5) -> dict:
    n = len(ds.y)
    edges = np.linspace(0.4 * n, n, folds + 1).astype(int)
    res = {"gbm": [], "ens": [], "base": []}
    for k in range(folds):
        tr_end, te_end = edges[k], edges[k + 1]
        va = int(tr_end * 0.85)
        Xtr, ytr, Xva, yva = ds.X[:va], ds.y[:va], ds.X[va:tr_end], ds.y[va:tr_end]
        Xte, yte, rrte = ds.X[tr_end:te_end], ds.y[tr_end:te_end], ds.rr[tr_end:te_end]
        if len(np.unique(ytr)) < 2 or len(yte) < 20:
            continue
        g = GBMModel(threads).fit(Xtr, ytr, Xva, yva)
        pg = g.predict(Xte)
        pe = pg
        if nn_enabled:
            nnm = SeqNet(threads).fit(ds.seq[:va], Xtr, ytr, ds.seq[va:tr_end], Xva, yva)
            pe = 0.5 * pg + 0.5 * nnm.predict(ds.seq[tr_end:te_end], Xte)
        r_all = outcomes_r(yte, rrte)
        for key, p in (("gbm", pg), ("ens", pe)):
            st = policy_stats(r_all[p >= threshold])
            res[key].append({"auc": auc(yte, p), "logloss": logloss(yte, p), **st})
        res["base"].append(policy_stats(r_all))
    agg = {k: {m: float(np.mean([f[m] for f in v])) for m in v[0]} if v else {} for k, v in res.items()}
    agg["folds"] = len(res["gbm"])
    return agg


def train_weekly(cfg, db, registry, histories: dict[str, pd.DataFrame], specs: dict) -> dict:
    """آموزش هفتگی. histories: {symbol: کندل‌های M5 تاریخی}"""
    L = cfg.get("learning")
    threads = int(L["max_train_threads"])
    t0 = time.time()
    sets = []
    for sym, df in histories.items():
        ds = build_dataset(cfg, sym, df, specs[sym])
        if ds is not None:
            sets.append(ds)
    if not sets:
        return {"ok": False, "reason": "داده‌ی کافی برای آموزش نیست"}
    ds = merge(sets) if len(sets) > 1 else sets[0]
    wf = walk_forward(ds, threads=threads, nn_enabled=bool(L["nn_enabled"]),
                      threshold=float(cfg.get("confluence", "ml_reject_below")))
    if not wf.get("folds"):
        return {"ok": False, "reason": "Walk-Forward ممکن نشد"}
    gbm, ens, base = wf["gbm"], wf["ens"], wf["base"]
    # شبکه‌ی عصبی فقط اگر واقعاً از LightGBM تنها بهتر بود
    nn_active = bool(L["nn_enabled"]) and ens.get("logloss", 9) < gbm["logloss"] and ens.get("exp", -9) > gbm["exp"]
    # مدل باید از «بدون فیلتر» بهتر باشد، وگرنه ذخیره نمی‌شود
    best = ens if nn_active else gbm
    useful = best["auc"] > 0.52 and best["exp"] > base["exp"]
    n = len(ds.y)
    va = int(n * 0.85)
    g = GBMModel(threads).fit(ds.X[:va], ds.y[:va], ds.X[va:], ds.y[va:])
    nnm = SeqNet(threads).fit(ds.seq[:va], ds.X[:va], ds.y[:va], ds.seq[va:], ds.X[va:], ds.y[va:]) if L["nn_enabled"] else None
    metrics = {"walk_forward": wf, "nn_active": nn_active, "samples": n, "gbm_backend": g.backend,
               "nn_backend": nnm.backend if nnm else "", "useful": useful, "seconds": round(time.time() - t0)}
    if not useful:
        db.alert("info", "training", "مدل جدید از حالت بدون فیلتر بهتر نبود و ذخیره نشد")
        return {"ok": False, "reason": "مدل جدید بهتر از baseline نبود", "metrics": metrics}
    mid = registry.save(Ensemble(g, nnm, ds.columns, nn_active, metrics), metrics)
    db.kv_set("challenger_since", int(time.time()))
    db.alert("info", "training", f"مدل چالشگر #{mid} ساخته شد و {L['shadow_days']} روز در حالت Shadow اجرا می‌شود")
    return {"ok": True, "model_id": mid, "metrics": metrics}


def evaluate_shadow(cfg, db, registry) -> dict | None:
    """بعد از دوره‌ی Shadow: مقایسه‌ی Champion و Challenger روی سیگنال‌های واقعی این دوره."""
    cid, _ = registry.challenger()
    if not cid:
        return None
    since = int(db.kv_get("challenger_since", 0) or 0)
    if time.time() - since < int(cfg.get("learning", "shadow_days")) * 86400:
        return None
    thr = float(cfg.get("confluence", "ml_reject_below"))
    rows = db.query("SELECT ml_prob, shadow_prob, payload FROM signals WHERE time>=? AND shadow_prob IS NOT NULL", (since,))
    champ_r, chall_r = [], []
    for r in rows:
        p = json.loads(r["payload"] or "{}")
        if "outcome_r" not in p:
            continue
        if r["ml_prob"] is None or r["ml_prob"] >= thr:
            champ_r.append(p["outcome_r"])
        if r["shadow_prob"] >= thr:
            chall_r.append(p["outcome_r"])
    a, b = policy_stats(np.array(champ_r)), policy_stats(np.array(chall_r))
    result = {"champion": a, "challenger": b}
    if b["n"] >= 15 and b["pf"] > a["pf"] and b["exp"] > a["exp"] and b["dd"] <= a["dd"]:
        registry.promote(cid, f"PF {b['pf']:.2f}>{a['pf']:.2f}، Expectancy {b['exp']:.2f}>{a['exp']:.2f}")
        result["promoted"] = True
    else:
        registry.reject_challenger("در دوره‌ی Shadow به‌طور واقعی بهتر نبود")
        result["promoted"] = False
    return result


def label_signal_outcomes(db, candles_loader, horizon: int) -> int:
    """برای سیگنال‌های قدیمی‌تر از horizon، نتیجه‌ی فرضی (Triple Barrier) را از کندل‌های ذخیره‌شده حساب می‌کند."""
    rows = db.query("SELECT id, time, symbol, direction, payload FROM signals WHERE payload NOT LIKE '%outcome_r%' "
                    "AND time < ?", (int(time.time()) - (horizon + 2) * 300,))
    done = 0
    for r in rows[:2000]:
        p = json.loads(r["payload"] or "{}")
        if not p.get("sl_dist") or not p.get("tp_dist"):
            continue
        df = candles_loader(r["symbol"], r["time"] - 600)
        if df is None or len(df) < horizon + 2:
            continue
        idx = int(np.searchsorted(df.index.view("int64") // 10 ** 9 + 300, r["time"]))
        idx = min(max(idx, 0), len(df) - 1)
        y = feats.triple_barrier(df, idx, int(r["direction"]), p["sl_dist"], p["tp_dist"], horizon)
        if y is None:
            continue
        p["outcome_r"] = p["tp_dist"] / p["sl_dist"] if y == 1 else -1.0
        db.execute("UPDATE signals SET payload=? WHERE id=?", (json.dumps(p), r["id"]))
        done += 1
    return done
