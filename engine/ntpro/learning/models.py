"""مدل‌های یادگیری ماشین: LightGBM (یا جایگزین) + شبکه‌ی عصبی سبک (TCN با PyTorch یا MLP با numpy).

خروجی هر دو: احتمال اینکه قیمت قبل از حد ضرر به حد سود برسد. این احتمال فقط بخشی از امتیاز Confluence است.
ضد Overfitting: داده‌ی Validation زمانی (نه تصادفی)، Early Stopping، Dropout، Regularization.
"""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("ntpro.models")


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    order = np.argsort(np.r_[pos, neg])
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


class GBMModel:
    """LightGBM اگر نصب باشد؛ وگرنه HistGradientBoosting سایکیت‌لرن؛ وگرنه رگرسیون لجستیک numpy."""
    kind = "gbm"

    def __init__(self, threads: int = 2):
        self.threads = threads
        self.model = None
        self.backend = ""
        self.columns: list[str] = []

    def fit(self, X: np.ndarray, y: np.ndarray, Xv: np.ndarray, yv: np.ndarray) -> "GBMModel":
        try:
            import lightgbm as lgb
            self.model = lgb.LGBMClassifier(
                n_estimators=600, learning_rate=0.03, num_leaves=15, max_depth=5, min_child_samples=40,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0, n_jobs=self.threads,
                verbose=-1)
            self.model.fit(X, y, eval_set=[(Xv, yv)], callbacks=[lgb.early_stopping(40, verbose=False)])
            self.backend = "lightgbm"
            return self
        except ImportError:
            pass
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
            self.model = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_depth=5,
                                                        min_samples_leaf=40, l2_regularization=2.0,
                                                        early_stopping=True, validation_fraction=0.15,
                                                        n_iter_no_change=30)
            self.model.fit(X, y)
            self.backend = "sklearn-hgb"
            return self
        except ImportError:
            pass
        self.model = NumpyLogistic().fit(X, y, Xv, yv)
        self.backend = "numpy-logistic"
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict_proba(X))[:, 1]


class NumpyLogistic:
    def fit(self, X, y, Xv, yv, l2: float = 1e-2, lr: float = 0.05, epochs: int = 400):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        self.w, self.b = np.zeros(Z.shape[1]), 0.0
        for _ in range(epochs):
            p = 1 / (1 + np.exp(-np.clip(Z @ self.w + self.b, -30, 30)))
            g = p - y
            self.w -= lr * (Z.T @ g / len(y) + l2 * self.w)
            self.b -= lr * g.mean()
        return self

    def predict_proba(self, X):
        p = 1 / (1 + np.exp(-(((X - self.mu) / self.sd) @ self.w + self.b)))
        return np.c_[1 - p, p]


class NumpyMLP:
    """MLP کوچک با Dropout و Adam و Early Stopping — جایگزین وقتی PyTorch نصب نیست."""

    def __init__(self, hidden: int = 32, dropout: float = 0.3, lr: float = 3e-3, l2: float = 1e-3, seed: int = 0):
        self.h, self.dropout, self.lr, self.l2 = hidden, dropout, lr, l2
        self.rng = np.random.default_rng(seed)

    def _forward(self, Z, train=False):
        a1 = np.maximum(0, Z @ self.W1 + self.b1)
        if train and self.dropout:
            mask = (self.rng.random(a1.shape) > self.dropout) / (1 - self.dropout)
            a1 = a1 * mask
        return a1, 1 / (1 + np.exp(-np.clip((a1 @ self.W2 + self.b2).ravel(), -30, 30)))

    def fit(self, X, y, Xv, yv, epochs: int = 200, batch: int = 128, patience: int = 15):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z, Zv = (X - self.mu) / self.sd, (Xv - self.mu) / self.sd
        d = Z.shape[1]
        self.W1 = self.rng.normal(0, np.sqrt(2 / d), (d, self.h))
        self.b1 = np.zeros(self.h)
        self.W2 = self.rng.normal(0, np.sqrt(1 / self.h), (self.h, 1))
        self.b2 = np.zeros(1)
        params = [self.W1, self.b1, self.W2, self.b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        best, best_params, bad, t = np.inf, None, 0, 0
        for _ in range(epochs):
            idx = self.rng.permutation(len(Z))
            for s in range(0, len(Z), batch):
                bi = idx[s: s + batch]
                a1, p = self._forward(Z[bi], train=True)
                g = (p - y[bi])[:, None] / len(bi)
                gW2 = a1.T @ g + self.l2 * self.W2
                gb2 = g.sum(0)
                da1 = (g @ self.W2.T) * (a1 > 0)
                gW1 = Z[bi].T @ da1 + self.l2 * self.W1
                gb1 = da1.sum(0)
                t += 1
                for k, gr in enumerate((gW1, gb1, gW2, gb2)):
                    m[k] = 0.9 * m[k] + 0.1 * gr
                    v[k] = 0.999 * v[k] + 0.001 * gr * gr
                    params[k] -= self.lr * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
            loss = logloss(yv, self._forward(Zv)[1])
            if loss < best - 1e-4:
                best, bad = loss, 0
                best_params = [p.copy() for p in params]
            else:
                bad += 1
                if bad >= patience:
                    break
        if best_params:
            self.W1, self.b1, self.W2, self.b2 = best_params
        return self

    def predict_proba(self, X):
        p = self._forward((X - self.mu) / self.sd)[1]
        return np.c_[1 - p, p]


class SeqNet:
    """شبکه‌ی عصبی روی توالی کندل + ویژگی‌های زمینه.

    با PyTorch: Temporal CNN (Conv1d dilated + Dropout) → ترکیب با ویژگی‌های جدولی.
    بدون PyTorch: MLP numpy روی ۱۶ کندل آخر + ویژگی‌های جدولی.
    """
    kind = "nn"

    def __init__(self, threads: int = 2):
        self.threads = threads
        self.backend = ""
        self.net = None

    @staticmethod
    def _flat(seq: np.ndarray, tab: np.ndarray) -> np.ndarray:
        return np.c_[seq[:, -16:, :].reshape(len(seq), -1), tab]

    def fit(self, seq, tab, y, seq_v, tab_v, y_v) -> "SeqNet":
        try:
            import torch
            self._fit_torch(torch, seq, tab, y, seq_v, tab_v, y_v)
            self.backend = "torch-tcn"
        except ImportError:
            self.net = NumpyMLP().fit(self._flat(seq, tab), y, self._flat(seq_v, tab_v), y_v)
            self.backend = "numpy-mlp"
        return self

    def _fit_torch(self, torch, seq, tab, y, seq_v, tab_v, y_v, epochs=60, patience=8):
        torch.set_num_threads(self.threads)
        nn = torch.nn
        self.tab_mu, self.tab_sd = tab.mean(0), tab.std(0) + 1e-9

        class TCN(nn.Module):
            def __init__(s, cin, ctab):
                super().__init__()
                s.conv = nn.Sequential(
                    nn.Conv1d(cin, 24, 3, padding=2, dilation=1), nn.ReLU(), nn.Dropout(0.2),
                    nn.Conv1d(24, 24, 3, padding=4, dilation=2), nn.ReLU(), nn.Dropout(0.2),
                    nn.Conv1d(24, 24, 3, padding=8, dilation=4), nn.ReLU(), nn.AdaptiveAvgPool1d(1))
                s.head = nn.Sequential(nn.Linear(24 + ctab, 32), nn.ReLU(), nn.Dropout(0.3), nn.Linear(32, 1))

            def forward(s, xs, xt):
                h = s.conv(xs.transpose(1, 2)).squeeze(-1)
                return s.head(torch.cat([h, xt], 1)).squeeze(-1)

        T = lambda a: torch.tensor(a, dtype=torch.float32)  # noqa: E731
        xs, xt, yy = T(seq), T((tab - self.tab_mu) / self.tab_sd), T(y)
        vs, vt, vy = T(seq_v), T((tab_v - self.tab_mu) / self.tab_sd), T(y_v)
        net = TCN(seq.shape[2], tab.shape[1])
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-3)
        lossf = nn.BCEWithLogitsLoss()
        best, best_state, bad = 1e9, None, 0
        for _ in range(epochs):
            net.train()
            perm = torch.randperm(len(yy))
            for s in range(0, len(yy), 128):
                bi = perm[s: s + 128]
                opt.zero_grad()
                loss = lossf(net(xs[bi], xt[bi]), yy[bi])
                loss.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(lossf(net(vs, vt), vy))
            if vl < best - 1e-4:
                best, bad = vl, 0
                best_state = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= patience:
                    break
        if best_state:
            net.load_state_dict(best_state)
        self.net = net

    def predict(self, seq: np.ndarray, tab: np.ndarray) -> np.ndarray:
        if self.backend == "torch-tcn":
            import torch
            self.net.eval()
            with torch.no_grad():
                xs = torch.tensor(seq, dtype=torch.float32)
                xt = torch.tensor((tab - self.tab_mu) / self.tab_sd, dtype=torch.float32)
                return torch.sigmoid(self.net(xs, xt)).numpy()
        return self.net.predict_proba(self._flat(seq, tab))[:, 1]

    def __getstate__(self):
        st = self.__dict__.copy()
        if self.backend == "torch-tcn":
            import io

            import torch
            buf = io.BytesIO()
            torch.save(self.net, buf)
            st["net"] = buf.getvalue()
        return st

    def __setstate__(self, st):
        self.__dict__.update(st)
        if self.backend == "torch-tcn" and isinstance(self.net, bytes):
            import io

            import torch
            self.net = torch.load(io.BytesIO(self.net), weights_only=False)


class Ensemble:
    """مجموعه‌ی مدل‌ها؛ شبکه‌ی عصبی فقط وقتی فعال است که در Walk-Forward از LightGBM تنها بهتر بوده باشد."""

    def __init__(self, gbm: GBMModel, nn: SeqNet | None, columns: list[str], nn_active: bool, metrics: dict):
        self.gbm, self.nn, self.columns, self.nn_active, self.metrics = gbm, nn, columns, nn_active, metrics

    def vector(self, tab: dict) -> np.ndarray:
        return np.array([[tab.get(c, 0.0) for c in self.columns]], dtype=np.float32)

    def predict_one(self, tab: dict, seq: np.ndarray | None) -> tuple[float, float | None]:
        x = self.vector(tab)
        pg = float(self.gbm.predict(x)[0])
        pn = None
        if self.nn is not None and seq is not None:
            pn = float(self.nn.predict(seq[None, ...], x)[0])
        if self.nn_active and pn is not None:
            return 0.5 * pg + 0.5 * pn, pn
        return pg, pn
