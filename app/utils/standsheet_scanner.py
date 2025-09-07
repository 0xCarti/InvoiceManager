import base64
import json
from io import BytesIO
from typing import Dict

import cv2
import qrcode


def generate_qr_code(payload: Dict[str, int]) -> str:
    """Return a base64-encoded PNG for the given payload."""
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(json.dumps(payload))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def decode_qr(path: str) -> Dict[str, int]:
    """Decode a QR code from the provided image path."""
    img = cv2.imread(path)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}
    return {}
