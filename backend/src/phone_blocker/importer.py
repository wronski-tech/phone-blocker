"""Runs directory sources, records each run, and removes entries a source no longer lists."""

import json
import traceback
from collections.abc import Callable
from datetime import timedelta
from types import ModuleType

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .directory import delete_organization, save_record
from .models import ImportRun, Organization, SourceState, utcnow
from .sources import USER_AGENT, ImportContext, bip, ceidg, nfz, uke

SOURCES: dict[str, ModuleType] = {"uke": uke, "bip": bip, "nfz": nfz, "ceidg": ceidg}
# What `import all` runs. CEIDG needs a token and days for its first import, so it runs
# in its own container (see compose.yaml).
DEFAULT_SOURCES = ["uke", "bip", "nfz"]

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
    alert: Callable[[str, str], None] = lambda title, message: None,
) -> ImportRun:
    """Import one source. Never raises: failures are logged, recorded on the run, and alerted."""
    module = SOURCES[source]
    with sessions.begin() as session:
        run = ImportRun(source=source, status="running", saved=0, removed=0, errors=0)
        session.add(run)
        fresh = set(session.scalars(select(Organization.source_id).where(
            Organization.source == source, Organization.fetched_at >= utcnow() - max_age,
        )))
        saved_state = session.get(SourceState, source)
    ctx = ImportContext(delay=module.DEFAULT_DELAY if delay is None else delay, log=log, fresh_ids=fresh,
                        state=json.loads(saved_state.state) if saved_state else {})
    ctx.checkpoint = lambda: _save_state(sessions, source, ctx.state)
    log(f"{source}: import started ({len(fresh)} entries fresh)")

    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
            if hasattr(module, "replace_all"):  # reference data replaced wholesale, e.g. UKE ranges
                with sessions.begin() as session:
                    run.saved = module.replace_all(session, client, ctx)
            elif getattr(module, "INCREMENTAL", False):
                _import_changes(sessions, source, module, ctx, client, run, block_threshold, limit, log)
            else:
                _import_records(sessions, source, module, ctx, client, run, block_threshold, limit, log)
        run.status = "success"
    except Exception as exc:  # keep the scheduler alive; the run row records what happened
        ctx.errors.append(traceback.format_exc())
        log(ctx.errors[-1])
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}"

    run.errors = ctx.error_count
    run.error_log = "\n".join(ctx.errors) or None
    run.finished_at = utcnow()
    with sessions.begin() as session:
        session.merge(run)
    log(f"{source}: {run.status}, saved {run.saved}, removed {run.removed}, errors {run.errors}"
        + (f" ({run.message})" if run.message else ""))
    if run.status == "failed" or (run.message or "").startswith("Refused"):
        alert(f"Import {source} {'failed' if run.status == 'failed' else 'needs a look'}",
              f"{run.message}\nRun {run.id}: saved {run.saved}, removed {run.removed}, errors {run.errors}")
    return run


def _import_records(
    sessions: sessionmaker[Session], source: str, module: ModuleType, ctx: ImportContext, client: httpx.Client,
    run: ImportRun, block_threshold: int, limit: int | None, log: Callable[[str], None],
) -> None:
    seen: set[str] = set()
    for source_id, record in module.iter_records(ctx, client):
        seen.add(source_id)
        if record is None:
            continue
        with sessions.begin() as session:
            save_record(session, source, record, block_threshold)
        if _counted(sessions, source, run, limit, log):
            run.message = f"Stopped at --limit {limit}; nothing removed"
            return
    run.removed, run.message = _remove_missing(sessions, source, seen, block_threshold)


def _import_changes(
    sessions: sessionmaker[Session], source: str, module: ModuleType, ctx: ImportContext, client: httpx.Client,
    run: ImportRun, block_threshold: int, limit: int | None, log: Callable[[str], None],
) -> None:
    for source_id, record in module.iter_records(ctx, client):
        with sessions.begin() as session:
            if record is not None:
                save_record(session, source, record, block_threshold)
            elif org := session.scalar(select(Organization).where(
                Organization.source == source, Organization.source_id == source_id,
            )):
                delete_organization(session, org, block_threshold)
                run.removed += 1
            else:
                continue
        if record is not None and _counted(sessions, source, run, limit, log):
            run.message = f"Stopped at --limit {limit}"
            return


def _counted(
    sessions: sessionmaker[Session], source: str, run: ImportRun, limit: int | None, log: Callable[[str], None]
) -> bool:
    """Count a saved entry, show progress on long runs, and say whether --limit is reached."""
    run.saved += 1
    if run.saved % 100 == 0:
        log(f"{source}: saved {run.saved}")
        with sessions.begin() as session:  # so the admin page shows progress of runs taking hours
            session.merge(run)
    return bool(limit and run.saved >= limit)


def _save_state(sessions: sessionmaker[Session], source: str, state: dict) -> None:
    with sessions.begin() as session:
        session.merge(SourceState(source=source, state=json.dumps(state), updated_at=utcnow()))


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
