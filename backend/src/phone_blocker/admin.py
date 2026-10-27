"""Small server-rendered admin page at /admin.

Shows the state of the database and import runs, lets you review and undo reports, and
fix how a number is labelled or blocked with personal settings (which imports never
overwrite). Log in with any user name and API_TOKEN as the password.
"""

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from .api import number_out
from .config import Settings
from .directory import (
    SPAM_CATEGORIES, delete_report, get_or_create_phone, save_rule, search_organizations, set_personal,
)
from .importer import DEFAULT_SOURCES
from .models import ImportRun, NumberRange, Organization, PhoneNumber, Report, Rule, SyncState, utcnow
from .monitoring import status
from .phone import InvalidNumber, format_international, format_prefix, normalize, normalize_prefix
from .sources.uke import FIRST_RESERVE_ID

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["phone"] = format_international
templates.env.filters["prefix"] = format_prefix
templates.env.globals["categories"] = SPAM_CATEGORIES | {"safe": "Bezpieczny"}
basic_auth = HTTPBasic(auto_error=False)


def admin_router(sessions: sessionmaker[Session], settings: Settings) -> APIRouter:
    def require_admin(
        request: Request, credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_auth)]
    ) -> None:
        if settings.api_token and (
            credentials is None
            or not secrets.compare_digest(credentials.password.encode(), settings.api_token.encode())
        ):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="phone-blocker admin"'})
        # Browsers resend Basic credentials automatically, so refuse forms posted from other sites.
        if request.method == "POST":
            origin = request.headers.get("origin") or request.headers.get("referer") or ""
            if urlsplit(origin).netloc != request.url.netloc:
                raise HTTPException(403, "Cross-site form submission")

    def get_session():
        with sessions() as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]
    router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)], include_in_schema=False)

    def page(request: Request, template: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, template, context)

    @router.get("", response_class=HTMLResponse)
    def dashboard(request: Request, session: SessionDep):
        def count(table, *where) -> int:
            return session.scalar(select(func.count()).select_from(table).where(*where))

        stats = {
            "Labelled numbers": count(PhoneNumber, PhoneNumber.label.is_not(None)),
            "Blocked numbers": count(PhoneNumber, PhoneNumber.blocked),
            "Personal settings": count(PhoneNumber, or_(PhoneNumber.personal_action.is_not(None),
                                                        PhoneNumber.personal_label.is_not(None))),
            "Reports, last 7 days": count(Report, Report.created_at >= utcnow() - timedelta(days=7)),
            "Reports in total": count(Report),
            "UKE number prefixes": count(NumberRange),
            "Sync version": session.scalar(select(SyncState.version)),
        }
        sources = session.execute(
            select(Organization.source, func.count()).group_by(Organization.source).order_by(Organization.source)
        ).all()
        runs = session.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(30)).all()
        return page(request, "dashboard.html", stats=stats, sources=sources, runs=runs,
                    reports=_recent_reports(session, 10), health=status(session, settings, DEFAULT_SOURCES))

    @router.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: int, session: SessionDep):
        run = session.get(ImportRun, run_id) or _not_found("Import run")
        return page(request, "run.html", run=run)

    @router.get("/reports", response_class=HTMLResponse)
    def reports(request: Request, session: SessionDep):
        return page(request, "reports.html", reports=_recent_reports(session, 200))

    @router.post("/reports/{report_id}/delete")
    def remove_report(report_id: int, session: SessionDep, back: Annotated[str, Form()] = "/admin/reports"):
        report = session.get(Report, report_id) or _not_found("Report")
        delete_report(session, report, settings.block_threshold)
        session.commit()
        return RedirectResponse(back if back.startswith("/admin") else "/admin", status_code=303)

    @router.get("/search", response_class=HTMLResponse)
    def search(request: Request, session: SessionDep, q: str = ""):
        try:
            return RedirectResponse(f"/admin/numbers/{normalize(q)}", status_code=303)
        except InvalidNumber:
            pass
        organizations = search_organizations(session, q, 100) if len(q.strip()) >= 2 else []
        return page(request, "search.html", q=q, organizations=organizations)

    @router.get("/numbers/{number}", response_class=HTMLResponse)
    def number_detail(request: Request, number: int, session: SessionDep):
        _check_number(number)
        phone = session.scalar(select(PhoneNumber).where(PhoneNumber.number == number))
        details = number_out(session, phone or PhoneNumber(number=number, label=None, blocked=False,
                                                           listings=[], reports=[]))
        return page(request, "number.html", n=details)

    @router.post("/numbers/{number}/personal")
    def update_personal(
        number: int,
        session: SessionDep,
        action: Annotated[str, Form()] = "",
        label: Annotated[str, Form(max_length=200)] = "",
    ):
        if action not in ("", "block", "allow"):
            raise HTTPException(422, "Unknown action")
        _check_number(number)
        phone = get_or_create_phone(session, number)
        set_personal(session, phone, action or None, label, settings.block_threshold)
        session.commit()
        return RedirectResponse(f"/admin/numbers/{number}", status_code=303)

    @router.get("/rules", response_class=HTMLResponse)
    def rules(request: Request, session: SessionDep, error: str | None = None, prefix: str = ""):
        unassigned = session.scalar(
            select(func.count()).select_from(NumberRange).where(NumberRange.operator_id >= FIRST_RESERVE_ID))
        return page(request, "rules.html", rules=session.scalars(select(Rule).order_by(Rule.prefix)).all(),
                    unassigned=unassigned, error=error, prefix=prefix)

    @router.post("/rules")
    def add_rule(
        request: Request,
        session: SessionDep,
        prefix: Annotated[str, Form()],
        action: Annotated[str, Form()],
        note: Annotated[str, Form(max_length=200)] = "",
    ):
        if action not in ("block", "allow"):
            raise HTTPException(422, "Unknown action")
        try:
            save_rule(session, normalize_prefix(prefix), action, note)
        except InvalidNumber as exc:
            return rules(request, session, error=str(exc), prefix=prefix)
        session.commit()
        return RedirectResponse("/admin/rules", status_code=303)

    @router.post("/rules/{rule_id}/delete")
    def remove_rule(rule_id: int, session: SessionDep):
        session.delete(session.get(Rule, rule_id) or _not_found("Rule"))
        session.commit()
        return RedirectResponse("/admin/rules", status_code=303)

    return router


def _recent_reports(session: Session, limit: int) -> list[Report]:
    return list(session.scalars(
        select(Report).options(joinedload(Report.phone_number)).order_by(Report.id.desc()).limit(limit)
    ))


def _check_number(number: int) -> None:
    try:
        normalize(f"+{number}")
    except InvalidNumber:
        _not_found("Phone number")


def _not_found(what: str):
    raise HTTPException(404, f"{what} not found")
