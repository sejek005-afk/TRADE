"""ناظر (Watchdog بیرونی): موتور را به‌صورت زیرفرایند اجرا می‌کند و اگر کرش کرد یا Heartbeat قطع شد،
دوباره راه‌اندازی می‌کند. فقط فرایند خودش را مدیریت می‌کند و به هیچ برنامه‌ی دیگری روی سرور دست نمی‌زند.

python -m ntpro.supervisor
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config as config_mod

HEARTBEAT_TIMEOUT = 180


def main() -> int:
    data = config_mod.DATA_DIR
    (data / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / "logs" / "supervisor.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    log = logging.getLogger("supervisor")
    lock = data / "supervisor.pid"
    if lock.exists():
        try:
            old = int(lock.read_text())
            if _alive(old) and old != os.getpid():
                log.info("supervisor already running (pid %s) — exit", old)
                return 0
        except ValueError:
            pass
    lock.write_text(str(os.getpid()))
    hb = data / "heartbeat"
    restarts = []
    while True:
        log.info("starting engine")
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):          # موتور با python.exe و بدون پنجره اجرا می‌شود تا خروجی‌اش لاگ شود
            exe = exe[:-len("pythonw.exe")] + "python.exe"
        console = open(data / "logs" / "engine_console.log", "a", encoding="utf-8")
        proc = subprocess.Popen([exe, "-m", "ntpro.main"], cwd=str(Path(__file__).resolve().parent.parent),
                                stdout=console, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = time.time()
        while proc.poll() is None:
            time.sleep(15)
            try:
                age = time.time() - float(hb.read_text())
            except Exception:
                age = 0 if time.time() - started < HEARTBEAT_TIMEOUT else HEARTBEAT_TIMEOUT + 1
            if time.time() - started > HEARTBEAT_TIMEOUT and age > HEARTBEAT_TIMEOUT:
                log.error("heartbeat stale (%.0fs) — restarting engine", age)
                proc.terminate()
                try:
                    proc.wait(30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
        code = proc.poll()
        if code in (2, 3):
            log.error("engine refused to start (code %s: port conflict/config). waiting 5 min", code)
            time.sleep(300)
        restarts = [t for t in restarts if time.time() - t < 3600] + [time.time()]
        delay = min(300, 5 * len(restarts))
        log.warning("engine exited (code %s). restart in %ss", code, delay)
        time.sleep(delay)


def _alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
