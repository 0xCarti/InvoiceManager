from pathlib import Path

from PIL import Image

from app.utils.standsheet_ocr import read_stand_sheet


def _dummy_image(tmp_path: Path) -> str:
    img_path = tmp_path / "dummy.png"
    Image.new("RGB", (10, 10), "white").save(img_path)
    return str(img_path)


def test_uses_tesseract_when_available(monkeypatch, tmp_path):
    path = _dummy_image(tmp_path)

    dummy = {"text": ["123"], "conf": ["85"], "line_num": ["1"]}
    monkeypatch.setattr(
        "app.utils.standsheet_ocr._tesseract_data", lambda p: dummy
    )
    monkeypatch.setattr(
        "app.utils.standsheet_ocr._get_reader",
        lambda: (_ for _ in ()).throw(
            AssertionError("EasyOCR should not be used")
        ),
    )

    result = read_stand_sheet(path)
    assert result == {"text": ["123"], "conf": [85.0], "line_num": [1]}


def test_falls_back_to_easyocr(monkeypatch, tmp_path):
    path = _dummy_image(tmp_path)
    monkeypatch.setattr(
        "app.utils.standsheet_ocr._tesseract_data", lambda p: None
    )

    class DummyReader:
        def readtext(self, _path, detail=1):
            return [((0, 0, 0, 0), "456", 0.9)]

    monkeypatch.setattr(
        "app.utils.standsheet_ocr._get_reader", lambda: DummyReader()
    )

    result = read_stand_sheet(path)
    assert result == {"text": ["456"], "conf": [90.0], "line_num": [1]}
