"""Runs directory sources, records each run, and removes entries a source no longer lists."""

import traceback
from collections.abc import Callable
from datetime import timedelta
from types import ModuleType

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .directory import delete_organization, save_record
from .models import ImportRun, Organization, utcnow
from .sources import USER_AGENT, ImportContext, bip, nfz

SOURCES: dict[str, ModuleType] = {"bip": bip, "nfz": nfz}

# A complete run normally drops a handful of entries. If a source suddenly lists far fewer
# (an upstream outage or format change), keep everything rather than wipe the directory.
MAX_REMOVED_SHARE = 0.1


def run_import(
    sessions: sessionmaker[Session],
    source: str,
    block_threshold: int,
    *,
    limit: int | None = None,
    max_age: timedelta = timedelta(days=7),
    delay: float | None = None,
    log: Callable[[str], None] = print,
) -> ImportRun:
    """Import one source. Never raises: failures are logged and recorded on the run."""
    module = SOURCES[source]
    with sessions.begin() as session:
        run = ImportRun(source=source, status="running", saved=0, removed=0, errors=0)
        session.add(run)
        fresh = set(session.scalars(select(Organization.source_id).where(
            Organization.source == source, Organization.fetched_at >= utcnow() - max_age,
        )))
    ctx = ImportContext(delay=module.DEFAULT_DELAY if delay is None else delay, log=log, fresh_ids=fresh)
    seen: set[str] = set()
    log(f"{source}: import started ({len(fresh)} entries fresh)")

    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
            for source_id, record in module.iter_records(ctx, client):
                seen.add(source_id)
                if record is None:
                    continue
                with sessions.begin() as session:
                    save_record(session, source, record, block_threshold)
                run.saved += 1
                if run.saved % 100 == 0:
                    log(f"{source}: saved {run.saved}")
                if limit and run.saved >= limit:
                    run.message = f"Stopped at --limit {limit}; nothing removed"
                    break
            else:
                run.removed, run.message = _remove_missing(sessions, source, seen, block_threshold)
        run.status = "success"
    except Exception as exc:  # keep the scheduler alive; the run row records what happened
        log(traceback.format_exc())
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}"

    run.errors = ctx.errors
    run.finished_at = utcnow()
    with sessions.begin() as session:
        session.merge(run)
    log(f"{source}: {run.status}, saved {run.saved}, removed {run.removed}, errors {run.errors}"
        + (f" ({run.message})" if run.message else ""))
    return run


def _remove_missing(
    sessions: sessionmaker[Session], source: str, seen: set[str], block_threshold: int
) -> tuple[int, str | None]:
    with sessions.begin() as session:
        existing = session.execute(
            select(Organization.id, Organization.source_id).where(Organization.source == source)
        ).all()
        missing = [org_id for org_id, source_id in existing if source_id not in seen]
        if len(missing) > max(10, MAX_REMOVED_SHARE * len(existing)):
            return 0, f"Refused to remove {len(missing)} of {len(existing)} entries; check the source"
        for org_id in missing:
            delete_organization(session, session.get(Organization, org_id), block_threshold)
    return len(missing), None
