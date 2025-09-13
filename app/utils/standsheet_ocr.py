"""OCR helper for reading stand sheets.

This module uses PaddleOCR to extract text from stand sheets and returns data in
the format of :func:`pytesseract.image_to_data` so existing parsing logic can
remain unchanged.
"""

from typing import Dict, List

import cv2

_paddle_reader = None


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
        _paddle_reader = PaddleOCR(
            use_angle_cls=False, lang="en", show_log=False
        )
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
