"""
Lab Reagent Inventory API v2.1
Run:  uvicorn main:app --reload
Docs: http://127.0.0.1:8000/docs
UI:   http://127.0.0.1:8000/dashboard
"""

import os
import tempfile
from datetime import timedelta
from typing import List, Optional

from fastapi import (
    FastAPI, HTTPException, Query, Depends, status,
    UploadFile, File, Form,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm

from models import InventoryItem, InventoryUpdate, UsageRecord, BarcodeQuery, ImportConfig
import sheets
from auth import (
    authenticate_user, create_access_token, require_admin,
    require_any_role, Token, ACCESS_TOKEN_EXPIRE_MINUTES,
)

app = FastAPI(
    title="Lab Reagent Inventory API",
    version="2.1.0",
    description="Lab inventory management with Google Sheets, JWT auth, usage tracking, barcode, inbound, and batch import.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "version": "2.1.0"}


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(404, "Dashboard not found — place index.html in /static")


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=Token, tags=["Auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        data={"sub": user["username"], "role": user["role"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token, token_type="bearer",
                 role=user["role"], username=user["username"])


@app.get("/auth/me", tags=["Auth"])
async def me(current_user: dict = Depends(require_any_role)):
    return current_user


# ── Inventory — READ ──────────────────────────────────────────────────────────

@app.get("/inventory", tags=["Inventory"])
def get_inventory(current_user: dict = Depends(require_any_role)):
    try:
        return sheets.get_all_items()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/inventory/search", tags=["Inventory"])
def search_inventory(
    q: str = Query(..., min_length=1),
    threshold: float = Query(0.65, ge=0.0, le=1.0),
    current_user: dict = Depends(require_any_role),
):
    try:
        return sheets.search_items(q, threshold=threshold)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/inventory/{item_id}", tags=["Inventory"])
def get_item(item_id: str, current_user: dict = Depends(require_any_role)):
    item = sheets.get_item_by_id(item_id)
    if not item:
        raise HTTPException(404, f"Item '{item_id}' not found")
    return item


# ── Inventory — WRITE (admin) ─────────────────────────────────────────────────

@app.post("/inventory", status_code=201, tags=["Inventory"])
def add_item(item: InventoryItem, current_user: dict = Depends(require_admin)):
    try:
        return sheets.add_item(item)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.patch("/inventory/{item_id}", tags=["Inventory"])
def update_item(item_id: str, updates: InventoryUpdate,
                current_user: dict = Depends(require_admin)):
    try:
        return sheets.update_item(item_id, updates)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/inventory/{item_id}", tags=["Inventory"])
def delete_item(item_id: str, current_user: dict = Depends(require_admin)):
    try:
        if not sheets.delete_item(item_id):
            raise HTTPException(404, f"Item '{item_id}' not found")
        return {"message": f"Item '{item_id}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Barcode ───────────────────────────────────────────────────────────────────

@app.get("/barcode/{barcode}", tags=["Barcode"])
def lookup_barcode(barcode: str, current_user: dict = Depends(require_any_role)):
    item = sheets.get_item_by_barcode(barcode)
    if not item:
        raise HTTPException(404, f"No item found for barcode '{barcode}'")
    return item


@app.post("/barcode/scan", tags=["Barcode"])
def scan_barcode(body: BarcodeQuery, current_user: dict = Depends(require_any_role)):
    item = sheets.get_item_by_barcode(body.barcode)
    if not item:
        raise HTTPException(404, f"No item found for barcode '{body.barcode}'")
    return item


# ── Usage Log ─────────────────────────────────────────────────────────────────

@app.post("/usage", tags=["Usage"])
def log_usage(usage: UsageRecord, current_user: dict = Depends(require_any_role)):
    try:
        return sheets.record_usage(usage, username=current_user["username"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/usage", tags=["Usage"])
def get_usage_log(
    item_id: str = Query(None),
    current_user: dict = Depends(require_any_role),
):
    try:
        return sheets.get_usage_log(item_id=item_id)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Alerts ────────────────────────────────────────────────────────────────────

@app.get("/alerts", tags=["Alerts"])
def get_alerts(current_user: dict = Depends(require_any_role)):
    try:
        from alerts import check_alerts
        low_stock, expiring_30, expiring_60 = check_alerts()
        return {
            "low_stock":    low_stock,
            "expiring_30d": [{"item": i, "status": s} for i, s in expiring_30],
            "expiring_60d": [{"item": i, "status": s} for i, s in expiring_60],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/alerts/send", tags=["Alerts"])
def send_alerts(current_user: dict = Depends(require_admin)):
    try:
        from alerts import run_daily_check
        run_daily_check()
        return {"message": "Alert check complete"}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Inbound ───────────────────────────────────────────────────────────────────

@app.post("/inbound/photo", tags=["Inbound"])
async def inbound_photo(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_any_role),
):
    """
    Upload a reagent label photo. Returns extracted fields (stub OCR).
    User reviews and corrects the fields before saving via POST /inventory.
    """
    try:
        from inbound import process_photo
        contents = await file.read()
        extracted = process_photo(contents, file.content_type or "image/jpeg")
        return {"filename": file.filename, "extracted": extracted}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Batch Excel Import ────────────────────────────────────────────────────────

@app.post("/import/excel", tags=["Import"])
async def import_excel(
    files: List[UploadFile] = File(default=[]),
    folder_path: Optional[str] = Form(default=None),
    mode: str = Form(default="merge"),
    current_user: dict = Depends(require_admin),
):
    """
    Batch import from uploaded .xlsx files and/or a server-side folder path.
    mode: merge (default) | skip | overwrite
    Returns an ImportReport.
    """
    try:
        from importer import run_import, import_from_folder
        from models import ImportReport

        all_paths = []

        # Save uploaded files to temp dir
        tmp_dir = None
        if files:
            tmp_dir = tempfile.mkdtemp(prefix="labtrack_import_")
            for f in files:
                if not f.filename:
                    continue
                dest = os.path.join(tmp_dir, f.filename)
                with open(dest, "wb") as fh:
                    fh.write(await f.read())
                all_paths.append(dest)

        # Folder path on server
        folder_report = ImportReport()
        if folder_path and folder_path.strip():
            folder_report = import_from_folder(folder_path.strip(), mode=mode)

        # File upload report
        file_report = run_import(all_paths, mode=mode) if all_paths else ImportReport()

        # Merge reports
        combined = ImportReport(
            files_processed=file_report.files_processed + folder_report.files_processed,
            rows_total=file_report.rows_total + folder_report.rows_total,
            created=file_report.created + folder_report.created,
            updated=file_report.updated + folder_report.updated,
            skipped=file_report.skipped + folder_report.skipped,
            errors=file_report.errors + folder_report.errors,
        )

        # Cleanup temp files
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return combined.dict()

    except Exception as e:
        raise HTTPException(500, str(e))


# ── Inventory Check ───────────────────────────────────────────────────────────

@app.get("/check", tags=["InventoryCheck"])
def inventory_check(
    q: str = Query(..., min_length=1, description="Search by name, CAS, location, or supplier"),
    threshold: float = Query(0.65, ge=0.0, le=1.0),
    current_user: dict = Depends(require_any_role),
):
    """
    Search inventory for matching items (used by Inventory Check feature).
    Returns ranked matches.
    """
    try:
        return sheets.search_items(q, threshold=threshold)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/check/photo", tags=["InventoryCheck"])
async def check_photo(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_any_role),
):
    """Upload a reagent photo → extract candidate fields → search inventory."""
    try:
        from inbound import process_photo
        contents = await file.read()
        extracted = process_photo(contents, file.content_type or "image/jpeg")
        # If name was extracted, auto-search
        results = []
        search_q = extracted.get("name") or extracted.get("cas_number") or ""
        if search_q:
            results = sheets.search_items(search_q)
        return {"extracted": extracted, "matches": results}
    except Exception as e:
        raise HTTPException(500, str(e))
