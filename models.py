from pydantic import BaseModel, validator, Field
from typing import Optional, List
from datetime import date
import re


class InventoryItem(BaseModel):
    id: str
    name: str
    cas_number: Optional[str] = ""
    supplier: Optional[str] = ""
    location: Optional[str] = ""
    quantity: float = Field(..., ge=0)
    unit: Optional[str] = ""
    expiration_date: Optional[str] = None
    low_stock_threshold: float = Field(0, ge=0)
    barcode: Optional[str] = ""

    @validator("expiration_date", pre=True, always=True)
    def validate_expiration_date(cls, v):
        if v is None or v == "":
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):
            raise ValueError("expiration_date must be YYYY-MM-DD or blank")
        date.fromisoformat(str(v))
        return str(v)

    @validator("quantity", "low_stock_threshold", pre=True)
    def coerce_numeric(cls, v):
        val = float(v)
        if val < 0:
            raise ValueError("Must be >= 0")
        return val


class InventoryUpdate(BaseModel):
    quantity: Optional[float] = Field(None, ge=0)
    location: Optional[str] = None
    supplier: Optional[str] = None
    expiration_date: Optional[str] = None
    low_stock_threshold: Optional[float] = Field(None, ge=0)
    barcode: Optional[str] = None
    name: Optional[str] = None
    cas_number: Optional[str] = None
    unit: Optional[str] = None

    @validator("expiration_date", pre=True, always=True)
    def validate_expiration_date(cls, v):
        if v is None or v == "":
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):
            raise ValueError("expiration_date must be YYYY-MM-DD or blank")
        date.fromisoformat(str(v))
        return str(v)


class UsageRecord(BaseModel):
    item_id: str
    quantity_used: float = Field(..., gt=0)
    used_by: Optional[str] = ""
    purpose: Optional[str] = ""
    notes: Optional[str] = ""


class BarcodeQuery(BaseModel):
    barcode: str


class ImportConfig(BaseModel):
    folder_path: Optional[str] = None
    mode: str = "merge"
    column_map: Optional[dict] = None


class ImportReport(BaseModel):
    files_processed: int = 0
    rows_total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = []
