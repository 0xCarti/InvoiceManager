from pathlib import Path

from PIL import Image

from app.utils.standsheet_ocr import read_stand_sheet


def _dummy_image(tmp_path: Path) -> str:
    img_path = tmp_path / "dummy.png"
    Image.new("RGB", (10, 10), "white").save(img_path)
    return str(img_path)


def test_uses_paddleocr(monkeypatch, tmp_path):
    path = _dummy_image(tmp_path)

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
