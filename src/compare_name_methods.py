"""
Compara, sobre todas las capturas ya procesadas, el nombre que lee
Tesseract (método viejo) contra el que lee el método híbrido con EasyOCR
(nuevo, name_recognition.py) — antes de confiar en el reemplazo. No escribe
nada en la base.

Uso: python src/compare_name_methods.py
"""
import glob
from pathlib import Path

import cv2

import layout
import ocr_extraction as ocr

ROOT = Path(__file__).resolve().parent.parent


def compare_image(path):
    raw = cv2.imread(path)
    if raw is None:
        return []
    image = layout.normalize_to_ref_width(raw)
    diffs = []
    for row in range(layout.NUM_ROWS):
        for side in ("blue", "red"):
            boxes = layout.get_row_boxes(row, side)
            crop_bgr = layout.crop(image, boxes["name"])
            old = ocr.clean_name(ocr.ocr_text(ocr.binarize(crop_bgr, scale=3)))
            new = ocr.leer_nombre_hibrido(image, boxes["name"])
            if old != new:
                diffs.append((f"{side}{row}", old, new))
    return diffs


if __name__ == "__main__":
    files = sorted(glob.glob(str(ROOT / "data" / "screenshots" / "procesadas" / "*.PNG")))
    print(f"Comparando nombres en {len(files)} capturas...\n")
    total = 0
    for path in files:
        diffs = compare_image(path)
        if diffs:
            print(f"{Path(path).name}:")
            for campo, old, new in diffs:
                print(f"  {campo}: tesseract={old!r}  easyocr={new!r}")
            total += len(diffs)
    print(f"\nTotal de diferencias: {total} sobre {len(files)} capturas")
