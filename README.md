# WhatsApp Audit Control Center

This project turns the earlier scripts into one connected system:

- `backend/` runs the FastAPI API, stores audits and faults, generates reports, and serves the PWA.
- `frontend/` is an installable dashboard for QR login, group selection, and live fault editing.
- `bot/` is a Baileys-based WhatsApp listener that syncs with the API.
- `backend/app/kew_pipeline.py` is the separate KEW automation pipeline for turning KEW CSV exports into a formatted Excel workbook.

## Quick start

### 1. Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

The backend defaults to a local SQLite database at `audit_system.db`.
Set `DATABASE_URL` if you want PostgreSQL instead.

### 2. Bot

```powershell
cd bot
npm install
npm start
```

### 3. Open the dashboard

Visit [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 4. Run the KEW pipeline

Use the floating `+` button in the dashboard, upload one or more KEW CSV files, and the app will generate a workbook you can download from the UI.

You can also:

- link the KEW workbook to the currently selected audit
- generate a one-click zip bundle containing the linked KEW workbook and the audit DOCX report

## Notes

- Dynamic user columns are stored safely as JSON-backed metadata instead of altering the table on every click.
- The bot writes images into `backend/media/images` so the API and dashboard can serve the same files.
- The parser keeps a rule-based path and supports optional Ollama fallback through `OLLAMA_URL` and `OLLAMA_MODEL`.
- KEW outputs are written under `backend/reports/kew/`.
- Bundle outputs are written under `backend/reports/bundles/`.
- If the launcher fails, check `.run/backend.stderr.log` and `.run/bot.stderr.log`.
