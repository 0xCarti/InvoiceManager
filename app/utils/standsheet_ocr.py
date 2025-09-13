"""OCR helper for reading stand sheets using EasyOCR.

This module lazily loads the EasyOCR model so importing this module does not
require the heavy dependency to be immediately available.  The exposed
``read_stand_sheet`` function returns data in a format similar to
``pytesseract.image_to_data`` so existing parsing logic can remain unchanged.
"""

from typing import Dict, List

_reader = None


def _get_reader():
    """Return a cached EasyOCR reader instance."""
    global _reader
    if _reader is None:
        try:
            import easyocr  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "easyocr is required to read stand sheets"
            ) from exc
        _reader = easyocr.Reader(["en"], gpu=False)
    return _reader


def read_stand_sheet(path: str) -> Dict[str, List]:
    """Read an image file and return OCR data.

    The returned dictionary contains ``text``, ``conf`` and ``line_num`` lists,
    matching the structure produced by ``pytesseract.image_to_data``.
    """

    reader = _get_reader()
    results = reader.readtext(path, detail=1)
    data: Dict[str, List] = {"text": [], "conf": [], "line_num": []}
    for idx, _res in enumerate(results, start=1):
        # Each result is (bbox, text, confidence)
        _, txt, conf = _res
        data["text"].append(txt)
        # EasyOCR returns confidence in range [0,1]; scale to [0,100]
        data["conf"].append(float(conf) * 100)
        data["line_num"].append(idx)
    return data
