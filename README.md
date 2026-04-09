# WhatsApp Audit Control Center

This project turns the earlier scripts into one connected system:

- `backend/` runs the FastAPI API, stores audits and faults, generates reports, and serves the PWA.
- `frontend/` is an installable dashboard for QR login, group selection, and live fault editing.
- `bot/` is a Baileys-based WhatsApp listener that syncs with the API.
- `backend/app/kew_pipeline.py` is the separate KEW automation pipeline for turning KEW CSV exports into a formatted Excel workbook.

## Compatibility

- Operating systems: Windows 10/11, macOS, and Linux
- Python: 3.11 or newer recommended
- Node.js: 20 or newer recommended
- Browser/PWA: latest Chrome or Edge works best
- WhatsApp: one active linked session for the bot number is recommended

Important behavior:

- The bot now stores runtime data in an OS-local app-data folder by default instead of the project folder.
- This reduces issues caused by OneDrive syncing, locked report files, and WhatsApp auth files being reused across laptops.
- If QR does not appear on another laptop, make sure no other active bot session is using the same WhatsApp number.
- If the bot keeps connecting and disconnecting, it is usually a WhatsApp session conflict or an unstable network rather than a frontend problem.

## Quick start

### Cross-platform launcher

```powershell
python start_app.py
```

To stop it:

```powershell
python stop_app.py
```

This launcher works on Windows, macOS, and Linux as long as Python and Node are installed.

### 1. Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

The backend defaults to a local SQLite database in the OS-local runtime folder for the current user.
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
- The bot writes auth, media, database, and reports into the OS-local runtime directory by default.
- The parser keeps a rule-based path and supports optional Ollama fallback through `OLLAMA_URL` and `OLLAMA_MODEL`.
- KEW outputs are written under the runtime `reports/kew/` folder.
- Bundle outputs are written under the runtime `reports/bundles/` folder.
- If the launcher fails, check `.run/backend.stderr.log` and `.run/bot.stderr.log`.
