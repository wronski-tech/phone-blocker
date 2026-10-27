"""Push alerts (ntfy) and the checks behind /status."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import Settings
from .models import ImportRun, utcnow

# Imports run daily (BIP and NFZ take hours) and backups daily; allow for a missed round.
MAX_IMPORT_AGE = timedelta(days=3)
MAX_BACKUP_AGE = timedelta(days=2)


def send_alert(settings: Settings, title: str, message: str) -> None:
    """Push a high-priority notification. Never raises: an alert must not break its caller."""
    if not settings.ntfy_url:
        return
    headers = {"Title": title, "Priority": "high", "Tags": "warning"}
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {settings.ntfy_token}"
    try:
        httpx.post(settings.ntfy_url, content=message.encode(), headers=headers, timeout=10).raise_for_status()
    except httpx.HTTPError as exc:
        print(f"alert not sent ({exc}): {title}: {message}")


def status(session: Session, settings: Settings, sources: list[str]) -> dict:
    """Overall health: the database answers, every source imported recently, backups are fresh."""
    checks: dict[str, dict] = {}
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # the database being down is exactly what this reports
        return {"ok": False, "checks": {"database": {"ok": False, "error": str(exc)}}}
    checks["database"] = {"ok": True}

    for source in sources:
        last = session.scalar(select(func.max(ImportRun.finished_at)).where(
            ImportRun.source == source, ImportRun.status == "success"))
        checks[f"import:{source}"] = {"ok": _recent(last, MAX_IMPORT_AGE), "last_success": last}

    if settings.backup_dir:
        dumps = sorted(Path(settings.backup_dir).glob("*.dump"), key=lambda p: p.stat().st_mtime)
        newest = datetime.fromtimestamp(dumps[-1].stat().st_mtime, UTC).replace(tzinfo=None) if dumps else None
        checks["backup"] = {"ok": _recent(newest, MAX_BACKUP_AGE), "newest": newest,
                            "file": dumps[-1].name if dumps else None}

    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}


def _recent(when: datetime | None, max_age: timedelta) -> bool:
    return when is not None and utcnow() - when <= max_age
