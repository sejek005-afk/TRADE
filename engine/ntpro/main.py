"""نقطه‌ی شروع موتور: python -m ntpro.main"""
from __future__ import annotations

import argparse
import logging
import signal
import socket
import sys

from . import MAGIC, __version__, config as config_mod
from .logs import setup as setup_logs

log = logging.getLogger("ntpro")


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NeuroTrader Pro engine")
    ap.add_argument("--no-api", action="store_true")
    args = ap.parse_args(argv)

    data = config_mod.DATA_DIR
    data.mkdir(parents=True, exist_ok=True)
    setup_logs(data)
    from .engine import Engine
    eng = Engine(data)
    port = int(eng.cfg.get("api", "port"))
    host = eng.cfg.get("api", "host")
    if port == 8765:
        log.error("پورت 8765 مال برنامه‌ی دیگر است. در config.json پورت دیگری بگذارید.")
        return 2
    if not args.no_api and not port_free(host, port):
        log.error("پورت %s اشغال است (شاید برنامه‌ی دیگری یا نسخه‌ی دیگری از همین موتور). خروج بدون دست زدن به آن.", port)
        return 3

    eng.start()

    def _stop(*_):
        log.info("stopping…")
        eng.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    if args.no_api:
        signal.pause() if hasattr(signal, "pause") else eng._stop.wait()
        return 0

    import uvicorn
    from .api.app import create_app
    app = create_app(eng)
    code = app.state.auth.setup_code(data)          # کد اتصال گوشی (بدون رمز)
    ssl = {}
    fp = ""
    if eng.cfg.get("api", "tls"):
        from .security.tls import ensure_cert
        cert, key, fp = ensure_cert(data)
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    banner = [
        "=" * 64,
        f" NeuroTrader Pro {__version__}  |  magic {MAGIC}  |  mode {eng.cfg.get('mode')}",
        f" API: {'https' if ssl else 'http'}://<IP-سرور>:{port}",
        f" اثر انگشت گواهی (در اپ تأیید کنید): {fp}" if fp else "",
        f" کد اتصال گوشی: {code}" if code else "",
        "=" * 64,
    ]
    for line in banner:
        if line:
            log.info(line)
    (data / "FINGERPRINT.txt").write_text(fp, encoding="utf-8")
    uvicorn.run(app, host=host, port=port, log_level="warning", **ssl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
