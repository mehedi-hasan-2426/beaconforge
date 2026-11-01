import time
import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def identifier() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(100))
    key_digest: Mapped[str] = mapped_column(String(64), unique=True)
    signing_secret: Mapped[str] = mapped_column(String(128))
    deployment_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    deployment_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    incident_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    incident_end: Mapped[date | None] = mapped_column(Date, nullable=True)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("project_id", "external_id", name="uq_project_event"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(160))
    delivery_id: Mapped[str] = mapped_column(String(160))
    payload_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="accepted")
    received_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    processed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Delivery(Base):
    __tablename__ = "deliveries"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    payload_digest: Mapped[str] = mapped_column(String(64))


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint("event_id", "revision", "purpose", name="uq_event_dispatch"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str] = mapped_column(String(16), default="process")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    published_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Rollup(Base):
    __tablename__ = "rollups"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON)


class Database:
    def __init__(self, url: str) -> None:
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                options["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
