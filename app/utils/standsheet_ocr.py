"""OCR helper for reading stand sheets.

This module uses PaddleOCR to extract text from stand sheets and returns data in
the format of :func:`pytesseract.image_to_data` so existing parsing logic can
remain unchanged.
"""

from typing import Dict, List

import cv2

_paddle_reader = None


def _tesseract_data(
    _path: str,
) -> Dict[str, List] | None:  # pragma: no cover - legacy stub
    """Placeholder for removed Tesseract-based implementation.

    The original project attempted Tesseract OCR before falling back to
    PaddleOCR.  The dependency was dropped, but tests still monkeypatch this
    function to short‑circuit the old behaviour.  Providing a stub keeps that
    patching working without requiring pytesseract at runtime.
    """

    return None


def _get_reader():  # pragma: no cover - legacy stub
    """Placeholder for the deprecated EasyOCR reader factory."""

    return None


def _get_paddle_reader():
    """Return a cached PaddleOCR reader instance."""
    global _paddle_reader
    if _paddle_reader is None:
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "paddleocr is required to read stand sheets",
            ) from exc
        # ``show_log`` was removed in recent versions of ``paddleocr``.  Passing
        # it now raises ``ValueError: Unknown argument: show_log`` which breaks
        # stand sheet scanning.  The default behaviour is to display minimal
        # logging so we simply omit the argument for compatibility with newer
        # releases.
        _paddle_reader = PaddleOCR(use_angle_cls=False, lang="en")
    return _paddle_reader


def read_stand_sheet(path: str) -> Dict[str, List]:
    """Read an image file and return OCR data.

    The returned dictionary mirrors ``pytesseract.image_to_data`` and includes
    positional fields so downstream parsing can determine token placement.
    """

    data: Dict[str, List] = {
        "text": [],
        "conf": [],
        "line_num": [],
        "left": [],
        "top": [],
        "width": [],
        "height": [],
    }

    reader = _get_paddle_reader()
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return data
    _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # ``paddlex`` expects a three-channel image.  ``cv2`` returns a two-dimensional
    # array when reading in grayscale, which causes ``IndexError: tuple index out of
    # range`` during normalization.  Converting back to BGR ensures the expected
    # shape.
    if img.ndim == 2:  # pragma: no cover - thin compatibility shim
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    results = reader.ocr(img)
    for idx, (box, (txt, conf)) in enumerate(results, start=1):
        if txt.strip():
            data["text"].append(txt)
            # PaddleOCR returns confidence in [0,1]; scale to [0,100]
            data["conf"].append(float(conf) * 100)
            data["line_num"].append(idx)
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            left = min(xs)
            top = min(ys)
            width = max(xs) - left
            height = max(ys) - top
            data["left"].append(int(left))
            data["top"].append(int(top))
            data["width"].append(int(width))
            data["height"].append(int(height))
    return data
