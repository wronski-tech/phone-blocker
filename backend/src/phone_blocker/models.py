from datetime import UTC, datetime

from sqlalchemy import BigInteger, ForeignKey, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    # Stored as naive UTC so SQLite and PostgreSQL behave the same.
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    # Named constraints let Alembic alter or drop them later, including on SQLite.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class PhoneNumber(Base):
    """One phone number and its effective caller-ID state.

    `label` and `blocked` are derived from listings and reports by
    `directory.refresh_number`. Every change to them takes a new `version`,
    which is what the iPhone uses for incremental sync.
    """

    __tablename__ = "phone_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # E.164 digits without '+', e.g. 48717777777 (CallKit format).
    number: Mapped[int] = mapped_column(BigInteger, unique=True)
    label: Mapped[str | None] = mapped_column(String(200))
    blocked: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    listings: Mapped[list["Listing"]] = relationship(back_populates="phone_number", order_by="Listing.id")
    reports: Mapped[list["Report"]] = relationship(back_populates="phone_number", order_by="Report.id")


class Organization(Base):
    """A public institution or business from the "yellow pages" side of the database."""

    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    street: Mapped[str | None] = mapped_column(String(300))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(200))
    commune: Mapped[str | None] = mapped_column(String(200))
    county: Mapped[str | None] = mapped_column(String(200))
    voivodeship: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(300))
    nip: Mapped[str | None] = mapped_column(String(20))
    regon: Mapped[str | None] = mapped_column(String(20))
    # Lowercase, diacritics folded ("urzad miejski wroclawia wroclaw") for search.
    search_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(50))  # importer name, e.g. "bip" or "nfz"
    source_id: Mapped[str] = mapped_column(String(1000))  # identity within the source, e.g. the BIP card URL
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    listings: Mapped[list["Listing"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", order_by="Listing.id"
    )


class Listing(Base):
    """A phone number published by an organization."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("organization_id", "phone_number_id", "kind", "department"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    phone_number_id: Mapped[int] = mapped_column(ForeignKey("phone_numbers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "phone" or "fax"
    department: Mapped[str | None] = mapped_column(String(200))  # e.g. "Redakcja BIP"

    organization: Mapped[Organization] = relationship(back_populates="listings")
    phone_number: Mapped[PhoneNumber] = relationship(back_populates="listings")


class Report(Base):
    """A user's report about a call from a number (sprawdzamnumer.pl-style)."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number_id: Mapped[int] = mapped_column(ForeignKey("phone_numbers.id"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    phone_number: Mapped[PhoneNumber] = relationship(back_populates="reports")


class NumberRange(Base):
    """A block of Polish numbers and the operator UKE assigned it to.

    `prefix` is national digits without the 48 country code; prefixes never overlap.
    """

    __tablename__ = "number_ranges"

    id: Mapped[int] = mapped_column(primary_key=True)
    prefix: Mapped[str] = mapped_column(String(15), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # landline, mobile, voip, service
    operator: Mapped[str] = mapped_column(String(300))
    operator_id: Mapped[int]  # see sources.uke.FIRST_RESERVE_ID
    zone: Mapped[str | None] = mapped_column(String(100))  # landline numbering zone, e.g. "WROCŁAW"
    service: Mapped[str | None] = mapped_column(String(300))  # 70x/80x service type


class ImportRun(Base):
    """One run of a directory importer, for monitoring and debugging."""

    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, success, failed
    saved: Mapped[int] = mapped_column(default=0)
    removed: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text)


class SyncState(Base):
    """Single row holding the last issued sync version.

    Incrementing it with UPDATE locks the row until commit, so versions become
    visible to readers in increasing order and incremental sync never skips one.
    """

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
