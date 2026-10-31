"""لاگ کامل: فایل چرخشی + بافر حافظه برای «لاگ زنده» در اپ."""
from __future__ import annotations

import logging
import logging.handlers
import threading
from collections import deque
from pathlib import Path


class RingHandler(logging.Handler):
    def __init__(self, size: int = 2000):
        super().__init__()
        self.buf: deque = deque(maxlen=size)
        self.seq = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self.seq += 1
            self.buf.append({"id": self.seq, "time": record.created, "level": record.levelname,
                             "name": record.name, "msg": self.format(record)})

    def since(self, last_id: int = 0, limit: int = 300) -> list[dict]:
        with self._lock:
            return [r for r in self.buf if r["id"] > last_id][-limit:]


RING = RingHandler()


def setup(data_dir: Path, level: int = logging.INFO) -> None:
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.TimedRotatingFileHandler(data_dir / "logs" / "engine.log", when="midnight",
                                                   backupCount=30, encoding="utf-8")
    fh.setFormatter(fmt)
    RING.setFormatter(logging.Formatter("%(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    for h in (fh, RING, sh):
        root.addHandler(h)
