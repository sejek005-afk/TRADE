"""بکاپ خودکار روزانه: دیتابیس (معاملات، وزن‌ها)، مدل‌ها و تنظیمات."""
from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path


def run_backup(db, data_dir: Path, keep_days: int = 14) -> Path:
    bdir = data_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tmp_db = bdir / f"db-{stamp}.sqlite"
    db.backup_to(tmp_db)
    out = bdir / f"backup-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "ntpro.sqlite")
        for name in ("config.json", "master.key", "mt5.enc", "tls_cert.pem", "tls_key.pem"):
            p = data_dir / name
            if p.exists():
                z.write(p, name)
        mdir = data_dir / "models"
        if mdir.exists():
            for p in mdir.glob("*.pkl"):
                z.write(p, f"models/{p.name}")
    tmp_db.unlink(missing_ok=True)
    cutoff = time.time() - keep_days * 86400
    for p in bdir.glob("backup-*.zip"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
    return out


def restore(zip_path: Path, data_dir: Path) -> None:
    """بازگردانی دستی (موتور باید خاموش باشد)."""
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(data_dir / "restore_tmp")
    src = data_dir / "restore_tmp"
    shutil.copy2(src / "ntpro.sqlite", data_dir / "ntpro.sqlite")
    for p in src.iterdir():
        if p.is_file() and p.name != "ntpro.sqlite":
            shutil.copy2(p, data_dir / p.name)
    if (src / "models").exists():
        shutil.copytree(src / "models", data_dir / "models", dirs_exist_ok=True)
    shutil.rmtree(src)
