"""گزارش بک‌تست: وین‌ریت، Profit Factor، Expectancy، حداکثر Drawdown، Sharpe، معاملات ماهانه + مونت‌کارلو."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / np.where(peak > 0, peak, 1)
    return float(dd.max() * 100)


def metrics(trades: list[dict], equity: pd.Series | None, initial: float) -> dict:
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    r = np.array([t.get("r_multiple", 0.0) for t in trades], dtype=float)
    n = len(trades)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    out = {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (math.inf if gross_win > 0 else 0.0),
        "expectancy_r": round(float(r.mean()), 3) if n else 0.0,
        "expectancy_cash": round(float(pnl.mean()), 2) if n else 0.0,
        "net_profit": round(float(pnl.sum()), 2),
        "return_pct": round(float(pnl.sum()) / initial * 100, 2),
        "avg_win_r": round(float(r[r > 0].mean()), 2) if (r > 0).any() else 0.0,
        "avg_loss_r": round(float(r[r <= 0].mean()), 2) if (r <= 0).any() else 0.0,
    }
    if equity is not None and len(equity):
        out["max_drawdown_pct"] = round(max_drawdown(equity.to_numpy()), 2)
        daily = equity.resample("1D").last().dropna()
        rets = daily.pct_change().dropna()
        out["sharpe"] = round(float(rets.mean() / rets.std() * math.sqrt(252)), 2) if len(rets) > 2 and rets.std() > 0 else 0.0
    else:
        eq = initial + np.cumsum(pnl)
        out["max_drawdown_pct"] = round(max_drawdown(np.r_[initial, eq]), 2)
        out["sharpe"] = 0.0
    if n:
        df = pd.DataFrame({"t": pd.to_datetime([t["exit_time"] for t in trades], utc=True), "pnl": pnl})
        m = df.groupby(df["t"].dt.strftime("%Y-%m"))["pnl"].agg(["count", "sum"])
        out["monthly"] = {k: {"trades": int(v["count"]), "pnl": round(float(v["sum"]), 2)} for k, v in m.iterrows()}
    else:
        out["monthly"] = {}
    return out


def monte_carlo(trades: list[dict], initial: float, runs: int = 2000, seed: int = 0) -> dict:
    """جابه‌جایی ترتیب معاملات برای تخمین بدترین Drawdown محتمل."""
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    if len(pnl) < 5:
        return {"runs": 0}
    rng = np.random.default_rng(seed)
    dds = np.empty(runs)
    for k in range(runs):
        eq = initial + np.cumsum(rng.permutation(pnl))
        dds[k] = max_drawdown(np.r_[initial, eq])
    return {"runs": runs, "dd_median": round(float(np.median(dds)), 2), "dd_p95": round(float(np.percentile(dds, 95)), 2),
            "dd_p99": round(float(np.percentile(dds, 99)), 2), "dd_worst": round(float(dds.max()), 2)}


def breakdown(trades: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        vals = t.get(key)
        vals = vals if isinstance(vals, list) else [vals]
        for v in vals:
            groups.setdefault(str(v), []).append(t)
    return {k: {kk: vv for kk, vv in metrics(v, None, 10000).items() if kk != "monthly"} for k, v in groups.items()}


def full_report(result, mc_runs: int = 2000) -> dict:
    m = metrics(result.trades, result.equity, result.initial_balance)
    return {"symbol": result.symbol, "label": result.label, "signals": result.signals, **m,
            "monte_carlo": monte_carlo(result.trades, result.initial_balance, mc_runs),
            "by_strategy": breakdown(result.trades, "strategies"), "by_session": breakdown(result.trades, "session"),
            "by_regime": breakdown(result.trades, "regime")}


def to_text_fa(rep: dict) -> str:
    mc = rep.get("monte_carlo", {})
    lines = [
        f"نماد: {rep['symbol']} {rep.get('label', '')}",
        f"تعداد معامله: {rep['trades']} | وین‌ریت: {rep['win_rate']}٪ | Profit Factor: {rep['profit_factor']}",
        f"Expectancy: {rep['expectancy_r']}R ({rep['expectancy_cash']}$) | سود خالص: {rep['net_profit']}$ ({rep['return_pct']}٪)",
        f"حداکثر Drawdown: {rep['max_drawdown_pct']}٪ | Sharpe: {rep['sharpe']}",
    ]
    if mc.get("runs"):
        lines.append(f"مونت‌کارلو ({mc['runs']} بار): Drawdown میانه {mc['dd_median']}٪، ۹۵٪ {mc['dd_p95']}٪، بدترین {mc['dd_worst']}٪")
    return "\n".join(lines)
