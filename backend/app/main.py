from __future__ import annotations

import io
import re
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .kew_pipeline import build_kew_workbook
from .models import Audit, BotConfig, Fault, FaultColumn, KewRun
from .parser import parse_message
from .reports import generate_docx_report, generate_docx_report_uniform_images
from .schemas import AuditCreate, AuditRead, BotStatePatch, FaultColumnCreate, FaultUpdate, WhatsappMessageIn

CORE_COLUMNS = [
    {"name": "building", "label": "Building"},
    {"name": "location", "label": "Location"},
    {"name": "asset", "label": "Asset"},
    {"name": "fault_type", "label": "Fault Type"},
    {"name": "message", "label": "Message"},
    {"name": "image_path", "label": "Image"},
]

settings.media_dir.mkdir(parents=True, exist_ok=True)
settings.reports_dir.mkdir(parents=True, exist_ok=True)
KEW_OUTPUT_DIR = settings.reports_dir / "kew"
KEW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BUNDLE_OUTPUT_DIR = settings.reports_dir / "bundles"
BUNDLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BOT_AUTH_DIR = settings.frontend_dir.parent / "bot" / "auth"

app = FastAPI(title=settings.api_title)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def initialize_app() -> None:
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        bot = db.get(BotConfig, 1)
        if bot is None:
            db.add(BotConfig(id=1))
            db.commit()
    finally:
        db.close()


def get_or_create_bot_config(db: Session) -> BotConfig:
    bot = db.get(BotConfig, 1)
    if bot is None:
        bot = BotConfig(id=1)
        db.add(bot)
        db.commit()
        db.refresh(bot)
    return bot


def bot_auth_session_exists() -> bool:
    if not BOT_AUTH_DIR.exists():
        return False
    return any(path.is_file() for path in BOT_AUTH_DIR.iterdir())


def clear_stale_bot_state_if_session_missing(db: Session, bot: BotConfig) -> None:
    if bot_auth_session_exists():
        if bot.connection_status != "connected" and bot.available_groups:
            bot.available_groups = []
            bot.last_event_at = datetime.utcnow()
            db.commit()
            db.refresh(bot)
        return

    changed = False

    if bot.available_groups:
        bot.available_groups = []
        changed = True

    if bot.connection_status == "connected" and not bot.qr_code:
        bot.connection_status = "disconnected"
        changed = True

    if changed:
        bot.last_event_at = datetime.utcnow()
        db.commit()
        db.refresh(bot)


def reset_bot_runtime_state(bot: BotConfig, clear_monitored_groups: bool = False) -> None:
    bot.connection_status = "disconnected"
    bot.qr_code = None
    bot.available_groups = []
    bot.last_error = None
    if clear_monitored_groups:
        bot.monitored_groups = []
    bot.last_event_at = datetime.utcnow()


def validate_bot_session(request: Request, bot: BotConfig) -> None:
    expected = (bot.session_name or "").strip()
    if not expected or expected == "default":
        return

    incoming = (request.headers.get("X-Bot-Session") or "").strip()
    if incoming != expected:
        raise HTTPException(status_code=409, detail="Ignoring stale bot session")


def normalize_column_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()).strip("_")
    if not normalized:
        raise HTTPException(status_code=400, detail="Column name is empty")
    if normalized in {column["name"] for column in CORE_COLUMNS}:
        raise HTTPException(status_code=400, detail="That column already exists as a core field")
    return normalized


def list_custom_columns(db: Session) -> list[FaultColumn]:
    return db.query(FaultColumn).order_by(FaultColumn.created_at.asc()).all()


def serialize_fault(fault: Fault, custom_columns: list[FaultColumn]) -> dict:
    payload = {
        "id": fault.id,
        "audit_id": fault.audit_id,
        "date": str(fault.date),
        "building": fault.building,
        "location": fault.location,
        "asset": fault.asset,
        "fault_type": fault.fault_type,
        "message": fault.message,
        "image_path": fault.image_path,
        "image_url": f"/media/images/{fault.image_path}" if fault.image_path else None,
        "source_group_id": fault.source_group_id,
        "source_group_name": fault.source_group_name,
        "sender_name": fault.sender_name,
        "cluster_id": fault.cluster_id,
        "created_at": fault.created_at.isoformat(),
        "updated_at": fault.updated_at.isoformat(),
    }

    extras = fault.extra_data or {}
    for column in custom_columns:
        payload[column.name] = extras.get(column.name, "")

    return payload


def next_cluster_id(db: Session, audit_id: int, building: str, fault_type: str) -> int:
    existing = (
        db.query(Fault)
        .filter(
            Fault.audit_id == audit_id,
            Fault.building == building,
            Fault.fault_type == fault_type,
        )
        .first()
    )
    if existing:
        return existing.cluster_id

    current_max = (
        db.query(Fault.cluster_id)
        .filter(Fault.audit_id == audit_id)
        .order_by(Fault.cluster_id.desc())
        .first()
    )
    return (current_max[0] if current_max else 0) + 1


@app.on_event("startup")
def on_startup() -> None:
    initialize_app()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "date": date.today().isoformat()}


@app.get("/api/schema")
def get_schema(db: Session = Depends(get_db)) -> dict:
    return {
        "core_columns": CORE_COLUMNS,
        "custom_columns": [
            {"name": column.name, "label": column.label}
            for column in list_custom_columns(db)
        ],
    }


@app.get("/api/audits")
def list_audits(db: Session = Depends(get_db)) -> dict:
    audits = db.query(Audit).order_by(Audit.created_at.desc()).all()
    return {"audits": [AuditRead.model_validate(audit).model_dump() for audit in audits]}


@app.post("/api/audits")
def create_audit(payload: AuditCreate, db: Session = Depends(get_db)) -> dict:
    audit_name = payload.audit_name.strip()
    if not audit_name:
        raise HTTPException(status_code=400, detail="Audit name is required")

    audit = Audit(
        audit_name=audit_name,
        audit_type=payload.audit_type.strip() or "Electrical Audit",
        start_date=date.today(),
        end_date=date.today(),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    bot = get_or_create_bot_config(db)
    if bot.active_audit_id is None:
        bot.active_audit_id = audit.id
        bot.last_event_at = datetime.utcnow()
        db.commit()

    return {"audit": AuditRead.model_validate(audit).model_dump()}


@app.get("/api/audits/{audit_id}")
def get_audit(audit_id: int, db: Session = Depends(get_db)) -> dict:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return {"audit": AuditRead.model_validate(audit).model_dump()}


@app.get("/api/audits/{audit_id}/kew-runs")
def list_kew_runs(audit_id: int, db: Session = Depends(get_db)) -> dict:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    runs = (
        db.query(KewRun)
        .filter(KewRun.audit_id == audit_id)
        .order_by(KewRun.created_at.desc())
        .all()
    )
    return {
        "kew_runs": [
            {
                "id": run.id,
                "audit_id": run.audit_id,
                "output_name": run.output_name,
                "workbook_path": run.workbook_path,
                "file_name": Path(run.workbook_path).name,
                "download_url": f"/downloads/kew/{Path(run.workbook_path).name}",
                "source_files": run.source_files or [],
                "created_at": run.created_at.isoformat(),
            }
            for run in runs
        ]
    }


@app.get("/api/faults/{audit_id}")
def get_faults(audit_id: int, db: Session = Depends(get_db)) -> dict:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    custom_columns = list_custom_columns(db)
    faults = (
        db.query(Fault)
        .filter(Fault.audit_id == audit_id)
        .order_by(Fault.created_at.desc())
        .all()
    )
    return {"faults": [serialize_fault(fault, custom_columns) for fault in faults]}


@app.put("/api/faults/{fault_id}")
def update_fault(fault_id: int, payload: FaultUpdate, db: Session = Depends(get_db)) -> dict:
    fault = db.get(Fault, fault_id)
    if fault is None:
        raise HTTPException(status_code=404, detail="Fault not found")

    custom_columns = {column.name for column in list_custom_columns(db)}
    extra_data = dict(fault.extra_data or {})

    for key, value in payload.values.items():
        if key in {"building", "location", "asset", "fault_type", "message"}:
            setattr(fault, key, str(value or "").strip())
        elif key in custom_columns:
            extra_data[key] = value

    fault.extra_data = extra_data
    db.commit()
    db.refresh(fault)
    return {"fault": serialize_fault(fault, list_custom_columns(db))}


@app.post("/api/fault-columns")
def add_fault_column(payload: FaultColumnCreate, db: Session = Depends(get_db)) -> dict:
    name = normalize_column_name(payload.name)
    existing = db.query(FaultColumn).filter(FaultColumn.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Column already exists")

    column = FaultColumn(name=name, label=payload.label or payload.name.strip())
    db.add(column)
    db.commit()
    db.refresh(column)
    return {"column": {"name": column.name, "label": column.label}}


@app.delete("/api/fault-columns/{column_name}")
def delete_fault_column(column_name: str, db: Session = Depends(get_db)) -> dict:
    name = normalize_column_name(column_name)
    column = db.query(FaultColumn).filter(FaultColumn.name == name).first()
    if column is None:
        raise HTTPException(status_code=404, detail="Column not found")

    faults = db.query(Fault).all()
    for fault in faults:
        extra_data = dict(fault.extra_data or {})
        if name in extra_data:
            extra_data.pop(name)
            fault.extra_data = extra_data

    db.delete(column)
    db.commit()
    return {"deleted": name}


@app.post("/api/whatsapp")
def process_whatsapp(payload: WhatsappMessageIn, request: Request, db: Session = Depends(get_db)) -> dict:
    bot = get_or_create_bot_config(db)
    validate_bot_session(request, bot)
    audit_id = payload.audit_id or bot.active_audit_id
    if audit_id is None:
        raise HTTPException(status_code=400, detail="No active audit configured")

    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    message = (payload.message or "").strip()
    parsed_faults = parse_message(message, payload.override_fault, payload.override_asset)

    inserted = 0
    for parsed in parsed_faults:
        duplicate = (
            db.query(Fault)
            .filter(
                Fault.audit_id == audit_id,
                Fault.message == message,
                Fault.building == parsed.building,
                Fault.location == parsed.location,
                Fault.fault_type == parsed.fault_type,
            )
            .first()
        )
        if duplicate:
            continue

        fault = Fault(
            audit_id=audit_id,
            building=parsed.building,
            location=parsed.location,
            asset=parsed.asset,
            fault_type=parsed.fault_type,
            message=message or "Image-only submission",
            image_path=payload.image,
            source_group_id=payload.group_id,
            source_group_name=payload.group_name,
            sender_name=payload.sender_name,
            cluster_id=next_cluster_id(db, audit_id, parsed.building, parsed.fault_type),
        )
        db.add(fault)
        inserted += 1

    bot.last_event_at = datetime.utcnow()
    db.commit()
    return {"inserted": inserted, "audit_id": audit_id}


@app.post("/api/faults/{fault_id}/reclassify")
def reclassify_fault(fault_id: int, db: Session = Depends(get_db)) -> dict:
    fault = db.get(Fault, fault_id)
    if fault is None:
        raise HTTPException(status_code=404, detail="Fault not found")

    parsed = parse_message(fault.message or "", None, None)[0]
    fault.building = parsed.building
    fault.location = parsed.location
    fault.asset = parsed.asset
    fault.fault_type = parsed.fault_type
    fault.cluster_id = next_cluster_id(db, fault.audit_id, parsed.building, parsed.fault_type)
    db.commit()
    db.refresh(fault)
    return {"fault": serialize_fault(fault, list_custom_columns(db))}


@app.get("/api/bot/state")
def get_bot_state(db: Session = Depends(get_db)) -> dict:
    bot = get_or_create_bot_config(db)
    clear_stale_bot_state_if_session_missing(db, bot)
    return {
        "connection_status": bot.connection_status,
        "qr_code": bot.qr_code,
        "available_groups": bot.available_groups or [],
        "monitored_groups": bot.monitored_groups or [],
        "active_audit_id": bot.active_audit_id,
        "session_name": bot.session_name,
        "last_error": bot.last_error,
        "last_event_at": bot.last_event_at.isoformat() if bot.last_event_at else None,
    }


@app.post("/api/bot/claim")
def claim_bot_session(request: Request, db: Session = Depends(get_db)) -> dict:
    incoming = (request.headers.get("X-Bot-Session") or "").strip()
    if not incoming:
        raise HTTPException(status_code=400, detail="Missing bot session header")

    bot = get_or_create_bot_config(db)
    bot.session_name = incoming
    reset_bot_runtime_state(bot, clear_monitored_groups=False)
    db.commit()
    db.refresh(bot)
    return {"status": "claimed"}


@app.put("/api/bot/state")
def patch_bot_state(payload: BotStatePatch, request: Request, db: Session = Depends(get_db)) -> dict:
    bot = get_or_create_bot_config(db)
    validate_bot_session(request, bot)
    for field in payload.model_fields_set:
        setattr(bot, field, getattr(payload, field))

    bot.last_event_at = datetime.utcnow()
    db.commit()
    db.refresh(bot)
    return {"status": "updated"}


@app.put("/api/bot/config")
def update_bot_config(payload: BotStatePatch, db: Session = Depends(get_db)) -> dict:
    bot = get_or_create_bot_config(db)

    if payload.active_audit_id is not None:
        audit = db.get(Audit, payload.active_audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="Selected audit does not exist")
        bot.active_audit_id = payload.active_audit_id

    if payload.monitored_groups is not None:
        bot.monitored_groups = payload.monitored_groups

    bot.last_event_at = datetime.utcnow()
    db.commit()
    return {"status": "saved"}


@app.post("/api/bot/reset-state")
def reset_bot_state(clear_monitored_groups: bool = False, db: Session = Depends(get_db)) -> dict:
    bot = get_or_create_bot_config(db)
    reset_bot_runtime_state(bot, clear_monitored_groups=clear_monitored_groups)
    db.commit()
    return {"status": "reset"}


@app.post("/api/bot/logout")
def logout_bot(db: Session = Depends(get_db)) -> dict:
    if BOT_AUTH_DIR.exists():
        shutil.rmtree(BOT_AUTH_DIR, ignore_errors=True)

    bot = get_or_create_bot_config(db)
    reset_bot_runtime_state(bot, clear_monitored_groups=True)
    bot.last_error = "Logged out. Restart the bot to pair a new WhatsApp number."
    db.commit()
    return {"status": "logged_out"}


@app.get("/api/bot/qr-image")
def get_bot_qr_image(db: Session = Depends(get_db)) -> Response:
    bot = get_or_create_bot_config(db)
    if not bot.qr_code:
        raise HTTPException(status_code=404, detail="QR code not available")

    try:
        import qrcode
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail="qrcode dependency missing") from exc

    qr_image = qrcode.make(bot.qr_code)
    buffer = io.BytesIO()
    qr_image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@app.get("/api/reports/{audit_id}")
def build_report(audit_id: int, db: Session = Depends(get_db)) -> dict:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    file_path = generate_docx_report(db, audit, settings.reports_dir, settings.media_dir)
    return {
        "file": str(file_path),
        "file_name": file_path.name,
        "download_url": f"/downloads/{file_path.name}",
    }


@app.get("/api/reports/{audit_id}/uniform")
def build_uniform_report(audit_id: int, db: Session = Depends(get_db)) -> dict:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    file_path = generate_docx_report_uniform_images(db, audit, settings.reports_dir, settings.media_dir)
    return {
        "file": str(file_path),
        "file_name": file_path.name,
        "download_url": f"/downloads/{file_path.name}",
    }


@app.post("/api/kew/process")
async def process_kew_pipeline(
    audit_id: int | None = Form(None),
    output_name: str = Form("kew_report"),
    generate_bundle: bool = Form(False),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one KEW CSV file")
    if generate_bundle and audit_id is None:
        raise HTTPException(status_code=400, detail="Select an audit to generate a KEW + DOCX bundle")

    audit = None
    if audit_id is not None:
        audit = db.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="Selected audit does not exist")

    collected: list[tuple[str, bytes]] = []
    for file in files:
        if not file.filename:
            continue
        content = await file.read()
        if not content:
            continue
        collected.append((file.filename, content))

    if not collected:
        raise HTTPException(status_code=400, detail="Uploaded files were empty")

    workbook_path = build_kew_workbook(collected, KEW_OUTPUT_DIR, output_name)
    normalized_output_name = output_name.strip() or "kew_report"
    kew_run = KewRun(
        audit_id=audit_id,
        output_name=normalized_output_name,
        workbook_path=str(workbook_path),
        source_files=[name for name, _ in collected],
    )
    db.add(kew_run)
    db.commit()
    db.refresh(kew_run)

    response = {
        "kew_run": {
            "id": kew_run.id,
            "audit_id": kew_run.audit_id,
            "output_name": kew_run.output_name,
            "file_name": workbook_path.name,
            "download_url": f"/downloads/kew/{workbook_path.name}",
            "created_at": kew_run.created_at.isoformat(),
        },
        "file": str(workbook_path),
        "file_name": workbook_path.name,
        "download_url": f"/downloads/kew/{workbook_path.name}",
        "processed_files": [name for name, _ in collected],
    }

    if generate_bundle:
        if audit is None:
            raise HTTPException(status_code=400, detail="Select an audit to generate a KEW + DOCX bundle")
        bundle = _build_audit_bundle(db, audit, kew_run)
        response["bundle"] = bundle

    return response


def _build_audit_bundle(db: Session, audit: Audit, kew_run: KewRun) -> dict:
    workbook_path = Path(kew_run.workbook_path)
    if not workbook_path.exists():
        raise HTTPException(status_code=404, detail="The linked KEW workbook could not be found")

    docx_path = generate_docx_report(db, audit, settings.reports_dir, settings.media_dir)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", audit.audit_name.strip().lower()).strip("_") or f"audit_{audit.id}"
    bundle_path = BUNDLE_OUTPUT_DIR / f"{safe_name}_{audit.id}_bundle.zip"

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(workbook_path, arcname=workbook_path.name)
        archive.write(docx_path, arcname=Path(docx_path).name)

    return {
        "file": str(bundle_path),
        "file_name": bundle_path.name,
        "download_url": f"/downloads/bundles/{bundle_path.name}",
    }


@app.post("/api/audits/{audit_id}/bundle")
def generate_audit_bundle(
    audit_id: int,
    kew_run_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    query = db.query(KewRun).filter(KewRun.audit_id == audit_id)
    if kew_run_id is not None:
        query = query.filter(KewRun.id == kew_run_id)

    kew_run = query.order_by(KewRun.created_at.desc()).first()
    if kew_run is None:
        raise HTTPException(status_code=404, detail="No KEW workbook is linked to this audit yet")

    return _build_audit_bundle(db, audit, kew_run)


app.mount("/media/images", StaticFiles(directory=str(settings.media_dir)), name="images")
app.mount("/downloads", StaticFiles(directory=str(settings.reports_dir)), name="downloads")
app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
