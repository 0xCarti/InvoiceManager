from pathlib import Path

from PIL import Image

from app.utils.standsheet_ocr import read_stand_sheet


def _dummy_image(tmp_path: Path) -> str:
    img_path = tmp_path / "dummy.png"
    Image.new("RGB", (10, 10), "white").save(img_path)
    return str(img_path)

def test_read_stand_sheet_uses_paddleocr(monkeypatch, tmp_path):
    path = _dummy_image(tmp_path)

    # Pretend Tesseract and EasyOCR find nothing so PaddleOCR is used
    monkeypatch.setattr("app.utils.standsheet_ocr._tesseract_data", lambda p: None)

    class DummyReader:
        def readtext(self, _path, detail=1):
            return []

    monkeypatch.setattr("app.utils.standsheet_ocr._get_reader", lambda: DummyReader())

    class DummyPaddleReader:
        def ocr(self, _img):
            box = [[0, 0], [10, 0], [10, 10], [0, 10]]
            return [[box, ("123", 0.85)]]

    monkeypatch.setattr(
        "app.utils.standsheet_ocr._get_paddle_reader",
        lambda: DummyPaddleReader(),
    )

    result = read_stand_sheet(path)
    assert result == {
        "text": ["123"],
        "conf": [85.0],
        "line_num": [1],
        "left": [0],
        "top": [0],
        "width": [10],
        "height": [10],
    }

