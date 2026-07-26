"""
Compara, sobre todas las capturas ya procesadas, lo que lee Tesseract
(método actual) contra lo que lee el reconocedor por plantillas (nuevo,
digit_recognition.py) para rating, marcador y bloque de stats — antes de
reemplazar nada en el pipeline en serio. No escribe nada en la base.

Uso: python src/compare_digit_methods.py
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

    for box, campo in (
        (layout.SCORE_LEFT_BOX, "marcador izq"),
        (layout.SCORE_RIGHT_BOX, "marcador der"),
    ):
        old = ocr.ocr_header_number(image, box)
        new = ocr.ocr_header_number_template(image, box)
        if old != new:
            diffs.append((campo, old, new))

    for row in range(layout.NUM_ROWS):
        for side in ("blue", "red"):
            boxes = layout.get_row_boxes(row, side)

            old_rating = ocr.ocr_rating(image, boxes["badge_number"])
            new_rating = ocr.ocr_rating_template(image, boxes["badge_number"])
            if old_rating != new_rating:
                diffs.append((f"rating {side}{row}", old_rating, new_rating))

            stats_th = ocr.binarize(layout.crop(image, boxes["stats"]))
            old_nums = ocr.split_stats_block(stats_th)
            new_nums = ocr.split_stats_block_template(stats_th)
            if old_nums != new_nums:
                diffs.append((f"stats {side}{row}", old_nums, new_nums))

    return diffs


if __name__ == "__main__":
    files = sorted(glob.glob(str(ROOT / "data" / "screenshots" / "procesadas" / "*.PNG")))
    print(f"Comparando {len(files)} capturas...\n")
    total = 0
    for path in files:
        diffs = compare_image(path)
        if diffs:
            print(f"{Path(path).name}:")
            for campo, old, new in diffs:
                print(f"  {campo}: tesseract={old!r}  plantilla={new!r}")
            total += len(diffs)
    print(f"\nTotal de diferencias: {total} sobre {len(files)} capturas")
