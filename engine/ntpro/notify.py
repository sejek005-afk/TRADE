"""اطلاع‌رسانی: صف هشدارها در دیتابیس (اپ هنگام باز شدن/WebSocket می‌خواند) + ایمیل پشتیبان + FCM اختیاری.

چون FCM در ایران همیشه پایدار نیست، هشدارهای مهم علاوه بر اپ با ایمیل هم ارسال می‌شوند.
"""
from __future__ import annotations

import json
import logging
import smtplib
import threading
import urllib.request
from email.mime.text import MIMEText

log = logging.getLogger("ntpro.notify")

LEVEL_EMAIL = {"critical", "warning", "trade"}


class Notifier:
    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db
        self._lock = threading.Lock()

    def send(self, level: str, kind: str, message: str) -> int:
        aid = self.db.alert(level, kind, message)
        threading.Thread(target=self._deliver, args=(aid, level, kind, message), daemon=True).start()
        return aid

    def _deliver(self, aid: int, level: str, kind: str, message: str) -> None:
        n = self.cfg.get("notify")
        sent = False
        if n["email"].get("enabled") and level in LEVEL_EMAIL:
            sent |= self._email(f"NeuroTrader Pro — {kind}", message)
        if n["fcm"].get("enabled") and n["fcm"].get("server_key"):
            sent |= self._fcm(kind, message)
        if sent:
            self.db.execute("UPDATE alerts SET sent=1 WHERE id=?", (aid,))

    def _email(self, subject: str, body: str) -> bool:
        e = self.cfg.get("notify", "email")
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"], msg["From"], msg["To"] = subject, e["user"], e["to"]
            with smtplib.SMTP(e["smtp_host"], int(e["smtp_port"]), timeout=20) as s:
                s.starttls()
                s.login(e["user"], e["password"])
                s.send_message(msg)
            return True
        except Exception as ex:
            log.warning("email failed: %s", ex)
            return False

    def _fcm(self, title: str, body: str) -> bool:
        key = self.cfg.get("notify", "fcm", "server_key")
        try:
            data = json.dumps({"to": "/topics/ntpro", "notification": {"title": title, "body": body[:200]}}).encode()
            req = urllib.request.Request("https://fcm.googleapis.com/fcm/send", data=data,
                                         headers={"Authorization": f"key={key}", "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)   # noqa: S310
            return True
        except Exception as ex:
            log.warning("fcm failed: %s", ex)
            return False
