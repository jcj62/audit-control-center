from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class AuditCreate(BaseModel):
    audit_name: str = Field(min_length=3, max_length=255)
    audit_type: str = "Electrical Audit"


class AuditRead(BaseModel):
    id: int
    audit_name: str
    audit_type: str
    start_date: date
    end_date: date
    created_at: datetime

    model_config = {"from_attributes": True}


class WhatsappMessageIn(BaseModel):
    message: str = ""
    image: str | None = None
    audit_id: int | None = None
    override_fault: str | None = None
    override_asset: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    sender_name: str | None = None


class FaultColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)


class FaultUpdate(BaseModel):
    values: dict


class BotStatePatch(BaseModel):
    connection_status: str | None = None
    qr_code: str | None = None
    available_groups: list[dict] | None = None
    monitored_groups: list[str] | None = None
    active_audit_id: int | None = None
    session_name: str | None = None
    last_error: str | None = None
