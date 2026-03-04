# Lab Inventory API

FastAPI + Google Sheets inventory management system.

Dashboard:
http://127.0.0.1:8000/dashboard
<!--<<<<<<< HEAD
=======
# lab_inventory_v2.0

>>>>>>> 84e10514ba56b2666d65fa089c2a9cd40b9cb2f1-->
# 🧪 Lab Reagent Inventory System v2

Full-featured lab inventory management: Google Sheets database, FastAPI backend, JWT authentication, usage logging, barcode scanning, automated alerts, and a built-in web dashboard.

---

## 📁 Project Structure

```
lab_inventory_v2/
├── main.py            FastAPI app — all endpoints
├── sheets.py          Google Sheets CRUD + UsageLog
├── models.py          Pydantic validation models
├── alerts.py          Daily alert checker + email
├── auth.py            JWT auth — admin / user roles
├── static/
│   └── index.html     Web dashboard (served at /dashboard)
├── requirements.txt
├── .env.example       → copy to .env
└── credentials.json   Google Service Account key (never commit!)
```

---

## ⚙️ Setup (Windows 10, Python 3.11)

### 1. Install dependencies
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Google Service Account
1. [Google Cloud Console](https://console.cloud.google.com/) → new project
2. Enable **Google Sheets API** + **Google Drive API**
3. IAM → Service Accounts → Create → download JSON key → save as `credentials.json`
4. Share your Google Sheet (Editor) with the service account email

### 3. Google Sheet setup
Create a sheet tab named `Inventory` with row 1 headers:
```
id | name | cas_number | supplier | location | quantity | unit | expiration_date | low_stock_threshold | barcode
```
A `UsageLog` tab is created automatically on first usage.

### 4. Configure environment
```bat
copy .env.example .env
```
Edit `.env`:
- `SPREADSHEET_ID` — from your sheet URL: `.../d/THIS_PART/edit`
- `AUTH_SECRET_KEY` — generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
- Set admin/user credentials and email settings

### 5. Run
```bat
uvicorn main:app --reload
```
- **Dashboard:** http://127.0.0.1:8000/dashboard
- **API Docs:** http://127.0.0.1:8000/docs

---

## 🔐 Authentication

| Role  | Permissions |
|-------|-------------|
| admin | View + Add + Edit + Delete + Send alerts + All endpoints |
| user  | View inventory + Record usage + Barcode scan + View alerts |

Login via the web dashboard or `POST /auth/login` with form fields `username` + `password`.

---

## 🔌 API Reference

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/login` | Login → JWT token |
| GET  | `/auth/me` | Current user info |

### Inventory (view: any auth / mutate: admin)
| Method | Path | Description |
|--------|------|-------------|
| GET    | `/inventory` | All items |
| GET    | `/inventory/{id}` | Single item |
| GET    | `/inventory/search?q=` | Search |
| POST   | `/inventory` | Add item (admin) |
| PATCH  | `/inventory/{id}` | Update item (admin) |
| DELETE | `/inventory/{id}` | Delete item (admin) |

### Barcode (any auth)
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/barcode/{barcode}` | Lookup by barcode |
| POST | `/barcode/scan` | Body: `{"barcode": "..."}` |

### Usage Log (any auth)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/usage` | Record usage (auto-deducts qty) |
| GET  | `/usage` | Full log (filter: `?item_id=`) |

### Alerts
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/alerts` | View current alerts |
| POST | `/alerts/send` | Trigger email (admin) |

---

## 📧 Alerts Schedule (Windows Task Scheduler)

1. Open Task Scheduler → Create Basic Task
2. Trigger: **Daily** at 8:00 AM
3. Action: Start a program
   - Program: `C:\path\to\venv\Scripts\python.exe`
   - Arguments: `C:\path\to\lab_inventory_v2\alerts.py`

---

## 🌐 Deployment Options

### Option A — Local network (team on same WiFi/LAN)
```bat
uvicorn main:app --host 0.0.0.0 --port 8000
```
Share: `http://YOUR_PC_IP:8000/dashboard`

### Option B — Cloud (Railway, Render, or Fly.io — free tiers)
1. Push project to GitHub (exclude `credentials.json` and `.env`)
2. Set environment variables in the platform dashboard
3. Add `credentials.json` contents as a secret env var, then load it in code
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Option C — Ngrok (quick public URL for testing)
```bat
pip install pyngrok
ngrok http 8000
```

---

## 🗺️ Roadmap

- [ ] Photo-based inventory check (upload image → AI identifies reagent)
- [ ] Excel export endpoint (`/inventory/export`)
- [ ] SMS alerts (Twilio)
- [ ] Multi-user DB (replace env-var users with SQLite/Postgres)
- [ ] QR code generation for new items

---

## v2.1 Features

### Inbound
Navigate to **Inbound** in the sidebar.  
- **Manual Entry** — fill all fields and click *Save to Inventory* (admin only).  
- **Photo Upload** — drag or click to upload a reagent label image. Extracted fields appear in editable inputs; correct them then save (OCR is stubbed — fills blanks for you to complete manually).

### Inventory Check
Navigate to **Inventory Check**.  
- **Manual Search** — type any combination of name, CAS number, supplier, or location. Results show matching items with their current status. Click *Use* to log usage directly.  
- **Photo Check** — upload a label photo; the system extracts candidate fields and searches inventory for matches.

### Batch Excel Import (admin only)
Navigate to **Batch Import**.

**Excel column headers** (case-insensitive, aliases supported):  
`id`, `name`, `cas_number`/`cas`, `supplier`, `location`, `quantity`/`qty`, `unit`, `expiration_date`/`expiry`, `low_stock_threshold`/`threshold`, `barcode`

**Modes:**  
- `merge` (default) — update existing rows + create new ones  
- `skip` — skip rows whose ID already exists  
- `overwrite` — fully replace matching fields  

**Steps:**  
1. Select mode (merge/skip/overwrite)  
2. Upload `.xlsx` files **or** enter a server folder path (e.g. `C:\LabData\imports`)  
3. Click **Run Import**  
4. Review the import report (files processed, created, updated, skipped, errors)

Install dependency: `pip install openpyxl`

### Alerts — Quick Buttons
The dashboard now shows **Low Stock** and **Expiring Soon** count buttons at the top.  
Clicking either navigates directly to the Alerts tab filtered to that category.  
Supplier column is now visible in all alert tables.

### Supplier Field
Supplier is now fully searchable, displayed in the inventory table, included in add/edit forms, and shown in all alert/report views.
