"""
inbound.py — Photo-based and manual inbound processing.

Photo OCR is stubbed: the image is accepted and a best-effort parse
is attempted from the filename / EXIF description. In production,
replace _ocr_image() with a real OCR call (e.g. pytesseract, Google Vision API).
"""

import re
from typing import Optional


def _ocr_image(image_bytes: bytes, content_type: str) -> dict:
    """
    Stub OCR extractor.
    Replace with a real OCR implementation (pytesseract, Google Vision, etc.).
    Returns a dict of any fields that could be extracted.
    """
    # In a real implementation this would send image_bytes to an OCR engine
    # and return structured fields. For now we return an empty hint dict
    # so the UI shows blank editable fields the user can fill in manually.
    return {
        "name": "",
        "cas_number": "",
        "supplier": "",
        "location": "",
        "quantity": "",
        "unit": "",
        "expiration_date": "",
        "low_stock_threshold": "",
        "barcode": "",
        "_ocr_note": "OCR stub — please fill in fields manually.",
    }


def process_photo(image_bytes: bytes, content_type: str) -> dict:
    """Public entry point for photo inbound processing."""
    return _ocr_image(image_bytes, content_type)
