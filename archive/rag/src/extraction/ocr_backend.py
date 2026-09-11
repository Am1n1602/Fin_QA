from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_import_error: Optional[str] = None
try:
    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image

    _tesseract_cmd = os.environ.get("FINQA_TESSERACT_CMD")
    if _tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
except ImportError as e:  # pymupdf / pytesseract / pillow not installed
    fitz = None  # type: ignore[assignment]
    pytesseract = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _import_error = (
        f"ocr_dependencies_not_installed: {e} -- run `pip install -e .[ocr]` "
        f"(or `pip install pymupdf pytesseract pillow`) to enable OCR."
    )


@dataclass
class OcrResult:
    text: str
    ok: bool
    error: Optional[str] = None


def ocr_available() -> tuple[bool, Optional[str]]:
    """(available, reason_if_not). Cheap -- only checks import state, does
    not probe the Tesseract binary itself (see _check_tesseract_binary,
    which is probed lazily and cached, since it's a subprocess call)."""
    if _import_error:
        return False, _import_error
    return True, None


_tesseract_checked = False
_tesseract_missing_reason: Optional[str] = None


def _check_tesseract_binary() -> Optional[str]:
    """Probes the Tesseract binary once per process and caches the result
    (it's a subprocess call -- not something to repeat per-page). Returns
    None if the binary is found and working, else an explanatory string."""
    global _tesseract_checked, _tesseract_missing_reason
    if _tesseract_checked:
        return _tesseract_missing_reason
    _tesseract_checked = True
    if _import_error:
        _tesseract_missing_reason = _import_error
        return _tesseract_missing_reason
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        _tesseract_missing_reason = (
            f"tesseract_binary_not_found: {type(e).__name__}: {e} -- the "
            f"Tesseract-OCR program itself is not installed or not on PATH. "
            f"Install it from https://github.com/UB-Mannheim/tesseract/wiki, "
            f"then either let it add itself to PATH or set the "
            f"FINQA_TESSERACT_CMD environment variable to its tesseract.exe "
            f"path."
        )
    return _tesseract_missing_reason


def ocr_page(pdf_path: str | Path, page_number: int, dpi: int = 300) -> OcrResult:
    """
    Renders one 1-indexed page of `pdf_path` to an image at `dpi` and runs
    Tesseract OCR over it. Never raises: any failure (missing deps,
    missing binary, out-of-range page, a corrupt render, an OCR engine
    error) comes back as OcrResult(ok=False, error=...) instead.
    """
    available, reason = ocr_available()
    if not available:
        return OcrResult(text="", ok=False, error=reason)

    tess_reason = _check_tesseract_binary()
    if tess_reason:
        return OcrResult(text="", ok=False, error=tess_reason)

    try:
        doc = fitz.open(str(pdf_path))
        try:
            if page_number < 1 or page_number > doc.page_count:
                return OcrResult(
                    text="", ok=False,
                    error=f"page_out_of_range: requested page {page_number}, "
                          f"document has {doc.page_count} page(s)",
                )
            page = doc.load_page(page_number - 1)  # fitz pages are 0-indexed
            zoom = dpi / 72.0  # PDF's native unit is 72 dpi
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()
        text = pytesseract.image_to_string(img)
        return OcrResult(text=text, ok=True)
    except Exception as e:  # rendering or OCR-engine failure -- surface, don't hide
        return OcrResult(text="", ok=False, error=f"ocr_failed: {type(e).__name__}: {e}")
