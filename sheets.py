"""
Google Sheets interface — Inventory + UsageLog

Sheet 1 (tab: Inventory):
  id | name | cas_number | supplier | location | quantity | unit |
  expiration_date | low_stock_threshold | barcode

Sheet 2 (tab: UsageLog — auto-created):
  timestamp | item_id | item_name | quantity_used | unit |
  quantity_before | quantity_after | used_by | purpose | notes
"""

import os
from typing import Optional
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from models import InventoryItem, InventoryUpdate, UsageRecord

load_dotenv()

SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
SHEET_INVENTORY  = "Inventory"
SHEET_USAGE_LOG  = "UsageLog"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

INVENTORY_COLS = [
    "id", "name", "cas_number", "supplier", "location",
    "quantity", "unit", "expiration_date", "low_stock_threshold", "barcode",
]
USAGE_COLS = [
    "timestamp", "item_id", "item_name", "quantity_used", "unit",
    "quantity_before", "quantity_after", "used_by", "purpose", "notes",
]


# ── Connection ────────────────────────────────────────────────────────────────

def _get_sheet(name: str):
    creds  = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    wb     = client.open_by_key(SPREADSHEET_ID)
    try:
        return wb.worksheet(name)
    except gspread.WorksheetNotFound:
        if name == SHEET_USAGE_LOG:
            ws = wb.add_worksheet(title=name, rows=1000, cols=len(USAGE_COLS))
            ws.append_row(USAGE_COLS)
            return ws
        raise


def _normalize(row: dict) -> dict:
    return {
        "id":                  str(row.get("id", "")),
        "name":                str(row.get("name", "")),
        "cas_number":          str(row.get("cas_number", "")),
        "supplier":            str(row.get("supplier", "")),
        "location":            str(row.get("location", "")),
        "quantity":            float(row.get("quantity", 0) or 0),
        "unit":                str(row.get("unit", "")),
        "expiration_date":     str(row.get("expiration_date", "")) or None,
        "low_stock_threshold": float(row.get("low_stock_threshold", 0) or 0),
        "barcode":             str(row.get("barcode", "")),
    }


# ── Read ──────────────────────────────────────────────────────────────────────

def get_all_items() -> list[dict]:
    return [_normalize(r) for r in _get_sheet(SHEET_INVENTORY).get_all_records()]


def get_item_by_id(item_id: str) -> Optional[dict]:
    items = get_all_items()
    # Primary: exact ID match
    found = next((i for i in items if i["id"] == item_id), None)
    if found:
        return found
    # Fallback: match by name
    return next((i for i in items if i["name"].lower() == item_id.lower()), None)


def get_item_by_barcode(barcode: str) -> Optional[dict]:
    return next((i for i in get_all_items() if i["barcode"] == barcode), None)


def _fuzzy_score(query: str, text: str) -> float:
    """
    Return a relevance score 0.0–1.0 between query and text.
    Strategy:
      1. Exact substring match — score 1.0
      2. Any word starts-with query — score 0.9
      3. Per-word SequenceMatcher — typo tolerance, but only between
         words of similar length (length ratio >= 0.75) AND only when
         the similarity ratio itself >= 0.80.
         This prevents "eagle" from matching "reagent" via shared letters.
    """
    from difflib import SequenceMatcher
    if not text:
        return 0.0
    q, t = query.lower(), text.lower()

    # Exact substring — highest confidence
    if q in t:
        return 1.0

    # Strip punctuation from words for cleaner matching
    words = [w.strip("()[],.%:;") for w in t.split() if w.strip("()[],.%:;")]

    # Any word starts with query
    if any(w.startswith(q) for w in words):
        return 0.9

    # Per-word fuzzy — enforce length similarity + strong ratio threshold
    best = 0.0
    for w in words:
        shorter = min(len(q), len(w))
        longer  = max(len(q), len(w))
        if longer == 0:
            continue
        # Words must be similar in length (within 75%)
        if shorter / longer < 0.75:
            continue
        ratio = SequenceMatcher(None, q, w).ratio()
        # Must be a genuinely strong character match, not just letter overlap
        if ratio >= 0.80 and ratio > best:
            best = ratio

    return best


def search_items(query: str, threshold: float = 0.65) -> list[dict]:
    """
    Fuzzy search across name, CAS number, supplier, location, barcode, id.
    Results are sorted by best match score descending.
    threshold: minimum score (0.0–1.0). Default 0.65 keeps results precise.
    """
    q = query.strip()
    if not q:
        return get_all_items()

    FIELDS  = ["name", "cas_number", "supplier", "location", "barcode", "id"]
    WEIGHTS = {"name": 1.0, "cas_number": 0.9, "id": 0.8,
               "supplier": 0.7, "location": 0.7, "barcode": 0.6}

    scored = []
    for item in get_all_items():
        best = max(
            _fuzzy_score(q, str(item.get(f) or "")) * WEIGHTS.get(f, 0.5)
            for f in FIELDS
        )
        if best >= threshold:
            scored.append((best, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_index(sheet, item_id: str) -> tuple[Optional[int], Optional[dict]]:
    """Find a row by ID first, then fall back to matching by name."""
    records = sheet.get_all_records()
    # Primary: exact ID match
    for i, row in enumerate(records):
        if str(row.get("id", "")) == item_id:
            return i + 2, row
    # Fallback: match by name (case-insensitive) — handles items with blank/N/A IDs
    for i, row in enumerate(records):
        if str(row.get("name", "")).lower() == item_id.lower():
            return i + 2, row
    return None, None


def _duplicate_exists(name: str, cas: str, exclude_id: str = None) -> bool:
    for i in get_all_items():
        if exclude_id and i["id"] == exclude_id:
            continue
        if i["name"].lower() == name.lower() and i["cas_number"] == cas:
            return True
    return False


# ── Create ────────────────────────────────────────────────────────────────────

def add_item(item: InventoryItem) -> dict:
    sheet = _get_sheet(SHEET_INVENTORY)
    items = get_all_items()

    if any(i["id"] == item.id for i in items):
        raise ValueError(f"ID '{item.id}' already exists.")
    if item.cas_number and _duplicate_exists(item.name, item.cas_number):
        raise ValueError(f"'{item.name}' with CAS '{item.cas_number}' already exists.")

    sheet.append_row([
        item.id, item.name, item.cas_number, item.supplier, item.location,
        item.quantity, item.unit, item.expiration_date or "",
        item.low_stock_threshold, item.barcode or "",
    ], value_input_option="USER_ENTERED")
    return item.dict()


# ── Update ────────────────────────────────────────────────────────────────────

def update_item(item_id: str, updates: InventoryUpdate) -> dict:
    sheet = _get_sheet(SHEET_INVENTORY)
    row_idx, _ = _row_index(sheet, item_id)
    if row_idx is None:
        raise ValueError(f"Item '{item_id}' not found.")

    col_map = {col: idx + 1 for idx, col in enumerate(INVENTORY_COLS)}
    for field, value in updates.dict(exclude_none=True).items():
        col = col_map.get(field)
        if col:
            sheet.update_cell(row_idx, col, value if value is not None else "")

    return get_item_by_id(item_id)


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_item(item_id: str) -> bool:
    sheet = _get_sheet(SHEET_INVENTORY)
    row_idx, _ = _row_index(sheet, item_id)
    if row_idx is None:
        return False
    sheet.delete_rows(row_idx)
    return True


# ── Usage Log ─────────────────────────────────────────────────────────────────

def record_usage(usage: UsageRecord, username: str = "") -> dict:
    inv = _get_sheet(SHEET_INVENTORY)
    row_idx, current = _row_index(inv, usage.item_id)
    if row_idx is None:
        raise ValueError(f"Item '{usage.item_id}' not found.")

    qty_before = float(current.get("quantity", 0) or 0)
    if usage.quantity_used > qty_before:
        raise ValueError(
            f"Cannot use {usage.quantity_used} — only {qty_before} {current.get('unit','')} in stock."
        )

    qty_after = round(qty_before - usage.quantity_used, 6)
    inv.update_cell(row_idx, INVENTORY_COLS.index("quantity") + 1, qty_after)

    log = _get_sheet(SHEET_USAGE_LOG)
    log.append_row([
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        usage.item_id,
        current.get("name", ""),
        usage.quantity_used,
        current.get("unit", ""),
        qty_before,
        qty_after,
        usage.used_by or username,
        usage.purpose or "",
        usage.notes or "",
    ], value_input_option="USER_ENTERED")

    return {
        "item_id":        usage.item_id,
        "item_name":      current.get("name", ""),
        "quantity_used":  usage.quantity_used,
        "quantity_before": qty_before,
        "quantity_after":  qty_after,
        "unit":           current.get("unit", ""),
    }


def get_usage_log(item_id: str = None) -> list[dict]:
    records = _get_sheet(SHEET_USAGE_LOG).get_all_records()
    if item_id:
        return [r for r in records if str(r.get("item_id", "")) == item_id]
    return records