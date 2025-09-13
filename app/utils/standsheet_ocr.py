"""OCR helper for reading stand sheets.

This module first attempts to read stand sheets using the Tesseract engine via
``pytesseract`` which excels at printed text. If Tesseract is unavailable or
fails to return any results, it falls back to EasyOCR which is better at
deciphering handwritten numbers. The exposed ``read_stand_sheet`` function
returns data in a format similar to ``pytesseract.image_to_data`` so existing
parsing logic can remain unchanged.
"""

from typing import Dict, List

import cv2

_reader = None


def _get_reader():
    """Return a cached EasyOCR reader instance."""
    global _reader
    if _reader is None:
        try:
            import easyocr  # type: ignore
        except ImportError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "easyocr is required to read stand sheets",
            ) from exc
        _reader = easyocr.Reader(["en"], gpu=False)
    return _reader


def _tesseract_data(path: str):
    """Return OCR data from Tesseract or ``None`` if unavailable."""
    try:
        import pytesseract  # type: ignore
        from pytesseract import Output
    except Exception:  # pragma: no cover - import error handled below
        return None

    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    # Apply adaptive threshold to improve character recognition
    _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    try:
        data = pytesseract.image_to_data(
            img, output_type=Output.DICT, config="--oem 3 --psm 6"
        )
        return {
            "text": data.get("text", []),
            "conf": data.get("conf", []),
            "line_num": data.get("line_num", []),
            "left": data.get("left", []),
            "top": data.get("top", []),
            "width": data.get("width", []),
            "height": data.get("height", []),
        }
    except Exception:  # pragma: no cover - OCR failure
        return None


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

    tess = _tesseract_data(path)
    if tess:
        for text, conf, line, left, top, width, height in zip(
            tess["text"],
            tess["conf"],
            tess["line_num"],
            tess["left"],
            tess["top"],
            tess["width"],
            tess["height"],
        ):
            if text.strip():
                data["text"].append(text)
                data["conf"].append(float(conf))
                data["line_num"].append(int(line))
                data["left"].append(int(left))
                data["top"].append(int(top))
                data["width"].append(int(width))
                data["height"].append(int(height))

    if data["text"]:
        return data

    reader = _get_reader()
    results = reader.readtext(path, detail=1)
    for idx, (box, txt, conf) in enumerate(results, start=1):
        if txt.strip():
            data["text"].append(txt)
            # EasyOCR returns confidence in range [0,1]; scale to [0,100]
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
