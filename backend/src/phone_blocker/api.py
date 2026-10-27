import secrets
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .db import make_sessionmaker
from .directory import REPORT_CATEGORIES, SAFE, find_range, fold, get_or_create_phone, refresh_number
from .models import Listing, Organization, PhoneNumber, Report
from .phone import InvalidNumber, describe, format_international, normalize
from .sources.uke import FIRST_RESERVE_ID

ReportCategory = Literal[REPORT_CATEGORIES]  # type: ignore[valid-type]


class OrganizationPhoneOut(BaseModel):
    number: int
    formatted: str
    kind: str
    department: str | None


class OrganizationOut(BaseModel):
    id: int
    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    commune: str | None
    county: str | None
    voivodeship: str | None
    website: str | None
    email: str | None
    nip: str | None
    regon: str | None
    source: str
    source_id: str
    phones: list[OrganizationPhoneOut]


class ListingOut(BaseModel):
    kind: str
    department: str | None
    organization: OrganizationOut


class ReportOut(BaseModel):
    id: int
    category: str
    comment: str | None
    created_at: datetime


class ReportSummary(BaseModel):
    total: int
    spam: int
    safe: int
    by_category: dict[str, int]
    recent: list[ReportOut]


class NumberInfo(BaseModel):
    type: str = Field(description="mobile, fixed_line, voip, premium_rate, toll_free, shared_cost, … or unknown")
    region: str | None = Field(description="City for Polish landlines, otherwise the country")
    operator: str | None = Field(description="Operator UKE assigned the range to; for mobiles the original one")
    service: str | None = Field(description="Service type of 70x/80x numbers")
    allocated: bool | None = Field(
        description="False when UKE has not assigned the range to anyone (caller ID is likely spoofed); "
                    "None when unknown: foreign numbers, ranges missing from the UKE tables"
    )


class Personal(BaseModel):
    action: Literal["block", "allow"] | None = Field(
        default=None, description="block: always block; allow: never block and hide spam labels")
    label: str | None = Field(default=None, max_length=200, description="Your own caller-ID label")


class NumberOut(BaseModel):
    number: int
    formatted: str
    label: str | None
    blocked: bool
    personal: Personal
    info: NumberInfo
    listings: list[ListingOut]
    reports: ReportSummary


class PersonalEntry(Personal):
    number: int
    formatted: str


class ReportIn(BaseModel):
    number: str = Field(examples=["+48 22 123 45 67"])
    category: ReportCategory
    comment: str | None = Field(default=None, max_length=1000)


class DirectoryEntry(BaseModel):
    number: int
    label: str | None
    blocked: bool


class DirectoryPage(BaseModel):
    entries: list[DirectoryEntry]
    next_since: int
    has_more: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    sessions = make_sessionmaker(settings.database_url)

    def get_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if settings.api_token and not secrets.compare_digest(
            authorization or "", f"Bearer {settings.api_token}"
        ):
            raise HTTPException(401, "Invalid or missing API token")

    def parse_number(raw: str) -> int:
        try:
            return normalize(raw)
        except InvalidNumber as exc:
            raise HTTPException(422, str(exc)) from exc

    SessionDep = Annotated[Session, Depends(get_session)]
    app = FastAPI(title="Phone Blocker API", version="0.1.0")
    v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @v1.get("/numbers/{number}", response_model=NumberOut)
    def lookup_number(number: str, session: SessionDep) -> NumberOut:
        """Who is calling? Unknown but valid numbers return an empty result."""
        value = parse_number(number)
        phone = session.scalar(select(PhoneNumber).where(PhoneNumber.number == value))
        return number_out(session, phone or PhoneNumber(number=value, label=None, blocked=False, listings=[], reports=[]))

    @v1.post("/reports", response_model=NumberOut, status_code=201)
    def create_report(body: ReportIn, session: SessionDep) -> NumberOut:
        phone = get_or_create_phone(session, parse_number(body.number))
        phone.reports.append(Report(category=body.category, comment=body.comment))
        refresh_number(session, phone, settings.block_threshold)
        session.commit()
        return number_out(session, phone)

    @v1.delete("/reports/{report_id}", status_code=204)
    def delete_report(report_id: int, session: SessionDep) -> None:
        """Undo a report, e.g. one made by mistake."""
        report = session.get(Report, report_id)
        if report is None:
            raise HTTPException(404, "Report not found")
        phone = report.phone_number
        session.delete(report)
        refresh_number(session, phone, settings.block_threshold)
        session.commit()

    @v1.put("/numbers/{number}/personal", response_model=NumberOut)
    def set_personal(number: str, body: Personal, session: SessionDep) -> NumberOut:
        """Always block or never block a number, and/or give it your own label. Send nulls to clear."""
        phone = get_or_create_phone(session, parse_number(number))
        phone.personal_action = body.action
        phone.personal_label = (body.label or "").strip() or None
        refresh_number(session, phone, settings.block_threshold)
        session.commit()
        return number_out(session, phone)

    @v1.get("/personal", response_model=list[PersonalEntry])
    def list_personal(session: SessionDep) -> list[PersonalEntry]:
        """Your block list, allow list and personal labels."""
        phones = session.scalars(
            select(PhoneNumber)
            .where(or_(PhoneNumber.personal_action.is_not(None), PhoneNumber.personal_label.is_not(None)))
            .order_by(PhoneNumber.number)
        )
        return [
            PersonalEntry(number=p.number, formatted=format_international(p.number),
                          action=p.personal_action, label=p.personal_label)
            for p in phones
        ]

    @v1.get("/organizations", response_model=list[OrganizationOut])
    def search_organizations(
        session: SessionDep,
        q: Annotated[str, Query(min_length=2, description="Words to match in name or city")],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[OrganizationOut]:
        words = fold(q).split()
        orgs = session.scalars(
            select(Organization)
            .where(and_(*(Organization.search_text.contains(w, autoescape=True) for w in words)))
            .options(selectinload(Organization.listings).selectinload(Listing.phone_number))
            .order_by(Organization.name)
            .limit(limit)
        )
        return [organization_out(o) for o in orgs]

    @v1.get("/directory", response_model=DirectoryPage)
    def directory_changes(
        session: SessionDep,
        since: Annotated[int, Query(ge=0, description="next_since from the previous page; 0 for a full download")] = 0,
        limit: Annotated[int, Query(ge=1, le=50_000)] = 10_000,
    ) -> DirectoryPage:
        """Entries for the iPhone Call Directory extension, ordered by version.

        With since=0 only active entries are returned. With since>0 an entry
        whose label is null and blocked is false means "remove this number".
        """
        query = select(PhoneNumber).where(PhoneNumber.version > since)
        if since == 0:
            query = query.where(or_(PhoneNumber.label.is_not(None), PhoneNumber.blocked))
        rows = session.scalars(query.order_by(PhoneNumber.version).limit(limit + 1)).all()
        page = rows[:limit]
        return DirectoryPage(
            entries=[DirectoryEntry(number=p.number, label=p.label, blocked=p.blocked) for p in page],
            next_since=page[-1].version if page else since,
            has_more=len(rows) > limit,
        )

    app.include_router(v1)
    return app


def number_out(session: Session, phone: PhoneNumber) -> NumberOut:
    spam = Counter(r.category for r in phone.reports if r.category != SAFE)
    safe = sum(r.category == SAFE for r in phone.reports)
    kind, region = describe(phone.number)
    number_range = find_range(session, phone.number)
    assigned = number_range is not None and number_range.operator_id < FIRST_RESERVE_ID
    return NumberOut(
        number=phone.number,
        formatted=format_international(phone.number),
        label=phone.label,
        blocked=phone.blocked,
        personal=Personal(action=phone.personal_action, label=phone.personal_label),
        info=NumberInfo(
            type=kind,
            region=region,
            operator=number_range.operator if assigned else None,
            service=number_range.service if number_range else None,
            allocated=assigned if number_range else None,
        ),
        listings=[
            ListingOut(kind=l.kind, department=l.department, organization=organization_out(l.organization))
            for l in phone.listings
        ],
        reports=ReportSummary(
            total=len(phone.reports),
            spam=spam.total(),
            safe=safe,
            by_category=dict(spam),
            recent=[
                ReportOut(id=r.id, category=r.category, comment=r.comment, created_at=r.created_at)
                for r in reversed(phone.reports[-20:])
            ],
        ),
    )


def organization_out(org: Organization) -> OrganizationOut:
    return OrganizationOut(
        id=org.id,
        name=org.name,
        street=org.street,
        postal_code=org.postal_code,
        city=org.city,
        commune=org.commune,
        county=org.county,
        voivodeship=org.voivodeship,
        website=org.website,
        email=org.email,
        nip=org.nip,
        regon=org.regon,
        source=org.source,
        source_id=org.source_id,
        phones=[
            OrganizationPhoneOut(
                number=l.phone_number.number,
                formatted=format_international(l.phone_number.number),
                kind=l.kind,
                department=l.department,
            )
            for l in org.listings
        ],
    )
