"""درخواست HTTP سبک با کتابخانه‌ی استاندارد (بدون وابستگی اضافه)."""
from __future__ import annotations

import json
import urllib.request

UA = "Mozilla/5.0 (NeuroTraderPro)"


def get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - آدرس‌ها ثابت و داخلی‌اند
        return r.read()


def get_json(url: str, timeout: float = 10.0):
    return json.loads(get(url, timeout).decode("utf-8", "replace"))
