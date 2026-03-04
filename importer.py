"""
importer.py — Batch Excel import for Lab Inventory.

Supported modes:
  merge     – update existing rows; create new ones (default)
  skip      – skip rows whose ID already exists
  overwrite – fully replace existing rows (same as merge for field-level updates)

Column mapping (default, case-insensitive, strips whitespace):
  id | name | cas_number / cas | supplier | location | quantity | unit
  expiration_date / expiry / exp_date | low_stock_threshold / threshold | barcode
"""

import os
import glob
import re
from datetime import datetime, date
from typing import Optional

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from models import ImportReport


# ── Column name normaliser ────────────────────────────────────────────────────

_ALIASES = {
    "id": "id",
    "item_id": "id",
    "name": "name",
    "reagent_name": "name",
    "reagent": "name",
    "cas_number": "cas_number",
    "cas": "cas_number",
    "casnumber": "cas_number",
    "cas#": "cas_number",
    "supplier": "supplier",
    "vendor": "supplier",
    "manufacturer": "supplier",
    "location": "location",
    "storage": "location",
    "storage_location": "location",
    "quantity": "quantity",
    "qty": "quantity",
    "amount": "quantity",
    "stock": "quantity",
    "unit": "unit",
    "units": "unit",
    "expiration_date": "expiration_date",
    "expiry": "expiration_date",
    "expiry_date": "expiration_date",
    "exp_date": "expiration_date",
    "exp": "expiration_date",
    "expiration": "expiration_date",
    "low_stock_threshold": "low_stock_threshold",
    "threshold": "low_stock_threshold",
    "min_stock": "low_stock_threshold",
    "reorder_point": "low_stock_threshold",
    "barcode": "barcode",
    "barcode_id": "barcode",
    "qr": "barcode",
}


def _canon(header: str) -> Optional[str]:
    """Normalise an Excel header to an inventory field name."""
    key = re.sub(r"[\s\-/]+", "_", header.strip().lower())
    return _ALIASES.get(key)


def _parse_date(val) -> Optional[str]:
    """Return YYYY-MM-DD string or None."""
    if val is None or val == "":
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d") if isinstance(val, datetime) else val.isoformat()
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _parse_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ── Core parser ───────────────────────────────────────────────────────────────

def _parse_workbook(path: str, column_map: Optional[dict] = None) -> list[dict]:
    """Parse one .xlsx file into a list of raw dicts keyed by inventory field."""
    if not HAS_OPENPYXL:
        raise ImportError("openpyxl is not installed. Run: pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)

    # Find header row (first non-empty row)
    headers = None
    for row in rows_iter:
        if any(c is not None and str(c).strip() for c in row):
            raw_headers = [str(c).strip() if c is not None else "" for c in row]
            if column_map:
                # user-supplied explicit mapping takes priority
                headers = [column_map.get(h, _canon(h) or h) for h in raw_headers]
            else:
                headers = [_canon(h) or h for h in raw_headers]
            break

    if not headers:
        return []

    records = []
    for row in rows_iter:
        if all(c is None or str(c).strip() == "" for c in row):
            continue  # skip blank rows
        rec = {}
        for i, val in enumerate(row):
            if i < len(headers):
                rec[headers[i]] = val
        records.append(rec)

    wb.close()
    return records


def _normalise_record(raw: dict) -> dict:
    """Convert a raw parsed row into a clean inventory dict."""
    return {
        "id":                  _parse_str(raw.get("id")),
        "name":                _parse_str(raw.get("name")),
        "cas_number":          _parse_str(raw.get("cas_number")),
        "supplier":            _parse_str(raw.get("supplier")),
        "location":            _parse_str(raw.get("location")),
        "quantity":            _parse_float(raw.get("quantity"), 0.0),
        "unit":                _parse_str(raw.get("unit")),
        "expiration_date":     _parse_date(raw.get("expiration_date")),
        "low_stock_threshold": _parse_float(raw.get("low_stock_threshold"), 0.0),
        "barcode":             _parse_str(raw.get("barcode")),
    }


# ── Dedup helper ──────────────────────────────────────────────────────────────

def _find_existing(rec: dict, all_items: list[dict]) -> Optional[dict]:
    """Return matching existing item or None."""
    if rec["id"]:
        found = next((i for i in all_items if i["id"] == rec["id"]), None)
        if found:
            return found
    # Secondary dedup by (name, cas_number, supplier, location)
    if rec["name"]:
        for i in all_items:
            name_match = i["name"].lower() == rec["name"].lower()
            cas_match  = (rec["cas_number"] == "" or i["cas_number"] == rec["cas_number"])
            sup_match  = (rec["supplier"]   == "" or i["supplier"]   == rec["supplier"])
            loc_match  = (rec["location"]   == "" or i["location"]   == rec["location"])
            if name_match and cas_match and sup_match and loc_match:
                return i
    return None


# ── Auto-ID generator ─────────────────────────────────────────────────────────

def _gen_id(name: str, existing_ids: set) -> str:
    base = re.sub(r"[^a-zA-Z0-9]", "-", name.strip().upper())[:12].strip("-")
    if not base:
        base = "ITEM"
    candidate = base
    n = 1
    while candidate in existing_ids:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


# ── Public entry point ────────────────────────────────────────────────────────

def run_import(
    file_paths: list[str],
    mode: str = "merge",
    column_map: Optional[dict] = None,
) -> ImportReport:
    """
    Import one or more .xlsx files into Google Sheets inventory.
    Returns an ImportReport.
    """
    from sheets import get_all_items, add_item, update_item
    from models import InventoryItem, InventoryUpdate

    report = ImportReport(files_processed=0, rows_total=0,
                          created=0, updated=0, skipped=0, errors=[])

    if not file_paths:
        report.errors.append("No files provided.")
        return report

    # Snapshot of current inventory for dedup
    try:
        all_items = get_all_items()
    except Exception as e:
        report.errors.append(f"Could not load inventory: {e}")
        return report

    existing_ids = {i["id"] for i in all_items}

    for path in file_paths:
        if not os.path.isfile(path):
            report.errors.append(f"File not found: {path}")
            continue
        if not path.lower().endswith((".xlsx", ".xls")):
            report.errors.append(f"Skipped non-Excel file: {os.path.basename(path)}")
            continue

        report.files_processed += 1
        try:
            raw_rows = _parse_workbook(path, column_map)
        except Exception as e:
            report.errors.append(f"{os.path.basename(path)}: parse error — {e}")
            continue

        for row_num, raw in enumerate(raw_rows, start=2):
            report.rows_total += 1
            try:
                rec = _normalise_record(raw)

                if not rec["name"]:
                    report.skipped += 1
                    continue  # skip rows with no name

                existing = _find_existing(rec, all_items)

                if existing:
                    if mode == "skip":
                        report.skipped += 1
                        continue

                    # merge / overwrite: update mutable fields
                    upd_fields = {}
                    for field in ["quantity", "location", "supplier", "expiration_date",
                                  "low_stock_threshold", "barcode", "unit",
                                  "name", "cas_number"]:
                        new_val = rec.get(field)
                        if new_val is not None and new_val != "" and new_val != 0.0:
                            upd_fields[field] = new_val

                    if upd_fields:
                        upd = InventoryUpdate(**upd_fields)
                        update_item(existing["id"], upd)
                        # refresh snapshot
                        all_items = [i if i["id"] != existing["id"] else {**i, **upd_fields}
                                     for i in all_items]
                        report.updated += 1
                    else:
                        report.skipped += 1
                else:
                    # New item
                    if not rec["id"]:
                        rec["id"] = _gen_id(rec["name"], existing_ids)
                    existing_ids.add(rec["id"])

                    new_item = InventoryItem(
                        id=rec["id"],
                        name=rec["name"],
                        cas_number=rec["cas_number"],
                        supplier=rec["supplier"],
                        location=rec["location"],
                        quantity=rec["quantity"],
                        unit=rec["unit"],
                        expiration_date=rec["expiration_date"],
                        low_stock_threshold=rec["low_stock_threshold"],
                        barcode=rec["barcode"],
                    )
                    add_item(new_item)
                    all_items.append(rec)
                    report.created += 1

            except Exception as e:
                report.errors.append(
                    f"{os.path.basename(path)} row {row_num}: {e}"
                )

    return report


def import_from_folder(
    folder_path: str,
    mode: str = "merge",
    column_map: Optional[dict] = None,
) -> ImportReport:
    """Import all .xlsx files found in folder_path."""
    paths = glob.glob(os.path.join(folder_path, "*.xlsx")) + \
            glob.glob(os.path.join(folder_path, "*.xls"))
    if not paths:
        r = ImportReport()
        r.errors.append(f"No Excel files found in: {folder_path}")
        return r
    return run_import(paths, mode=mode, column_map=column_map)
