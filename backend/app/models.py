from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_name: Mapped[str] = mapped_column(String(255), index=True)
    audit_type: Mapped[str] = mapped_column(String(120), default="Electrical Audit")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    faults: Mapped[list["Fault"]] = relationship(
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="Fault.created_at.desc()",
    )


class Fault(Base):
    __tablename__ = "faults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id"), index=True)
    date: Mapped[date] = mapped_column(Date, default=date.today)
    building: Mapped[str] = mapped_column(String(255), default="unknown")
    location: Mapped[str] = mapped_column(String(255), default="unknown")
    asset: Mapped[str] = mapped_column(String(255), default="unknown")
    fault_type: Mapped[str] = mapped_column(String(255), default="general fault")
    message: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_group_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cluster_id: Mapped[int] = mapped_column(Integer, default=1)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    audit: Mapped["Audit"] = relationship(back_populates="faults")


class FaultColumn(Base):
    __tablename__ = "fault_columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BotConfig(Base):
    __tablename__ = "bot_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    connection_status: Mapped[str] = mapped_column(String(40), default="disconnected")
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    monitored_groups: Mapped[list] = mapped_column(JSON, default=list)
    available_groups: Mapped[list] = mapped_column(JSON, default=list)
    active_audit_id: Mapped[int | None] = mapped_column(ForeignKey("audits.id"), nullable=True)
    session_name: Mapped[str] = mapped_column(String(120), default="default")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_event_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KewRun(Base):
    __tablename__ = "kew_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audits.id"), nullable=True, index=True)
    output_name: Mapped[str] = mapped_column(String(255))
    workbook_path: Mapped[str] = mapped_column(String(500))
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
