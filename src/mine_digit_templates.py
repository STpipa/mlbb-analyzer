"""
Semilla para el reconocimiento de dígitos por plantillas (reemplazo de
Tesseract para rating/K/D/A/oro/marcador). Recorre las capturas ya
procesadas, aísla cada dígito individual (por componentes conexas, igual
que ya hace ocr_extraction.py) y le pide a Tesseract que lea ESE carácter
solo con psm 8 y psm 10. Cuando ambos coinciden, hay alta confianza de que
la lectura es correcta — esos casos son la semilla de las plantillas.

No reemplaza nada todavía: solo junta muestras en data/reference/digits_raw/
para revisar antes de convertirlas en plantillas de verdad.

Uso: python src/mine_digit_templates.py
"""
import glob
from collections import defaultdict
from pathlib import Path

import cv2
import pytesseract

import layout
import ocr_extraction as ocr

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "reference" / "digits_raw"
WHITELIST = "0123456789."


def read_single_char(crop) -> str | None:
    votes = set()
    for psm in (10, 8):
        txt = pytesseract.image_to_string(
            crop, config=f"--psm {psm} -c tessedit_char_whitelist={WHITELIST}"
        ).strip()
        if len(txt) == 1:
            votes.add(txt)
        else:
            return None
    return votes.pop() if len(votes) == 1 else None


def individual_digit_crops(th, min_area=60):
    """Todas las componentes conexas grandes de un recorte ya binarizado,
    como crops individuales (sin agrupar) — cada una es un candidato a
    dígito o punto suelto."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    crops = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        crops.append(th[y:y + h, x:x + w])
    return crops


def stats_block_crops(th):
    return individual_digit_crops(th, min_area=200)


def rating_digit_crops(th):
    """Descarta la decoración de la medalla (más ancha que alta) igual que
    ocr_rating, para no contaminar la semilla con crops que no son dígitos."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(s) for s in stats[1:] if s[4] > 80]
    return [th[y:y + h, x:x + w] for x, y, w, h, area in comps if w <= h]


def header_digit_crops(th):
    """Descarta la franja diagonal decorativa (blobs chicos) igual que
    ocr_header_number."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(s) for s in stats[1:] if s[4] > 100]
    if not comps:
        return []
    max_area = max(c[4] for c in comps)
    return [th[y:y + h, x:x + w] for x, y, w, h, area in comps if area > max_area * 0.4]


def mine_from_image(path: str, counter: dict):
    raw = cv2.imread(path)
    if raw is None:
        return
    image = layout.normalize_to_ref_width(raw)

    crops = []
    for row in range(layout.NUM_ROWS):
        for side in ("blue", "red"):
            boxes = layout.get_row_boxes(row, side)
            stats_th = ocr.binarize(layout.crop(image, boxes["stats"]))
            if stats_th is not None:
                crops.extend(stats_block_crops(stats_th))
            rating_th = ocr.binarize(layout.crop(image, boxes["badge_number"]), scale=6)
            if rating_th is not None:
                crops.extend(rating_digit_crops(rating_th))
    for box in (layout.SCORE_LEFT_BOX, layout.SCORE_RIGHT_BOX):
        th = ocr.binarize(layout.crop(image, box), scale=4)
        if th is not None:
            crops.extend(header_digit_crops(th))

    for crop in crops:
        padded = ocr.pad(crop)
        char = read_single_char(padded)
        if char is None:
            continue
        key = "punto" if char == "." else char
        dest = RAW_DIR / key
        dest.mkdir(parents=True, exist_ok=True)
        idx = counter[key]
        cv2.imwrite(str(dest / f"{idx}.png"), padded)
        counter[key] += 1


if __name__ == "__main__":
    files = sorted(glob.glob(str(ROOT / "data" / "screenshots" / "procesadas" / "*.PNG")))
    print(f"Minando dígitos de {len(files)} capturas...")
    counter = defaultdict(int)
    for path in files:
        mine_from_image(path, counter)

    print("\nMuestras de alta confianza juntadas por carácter:")
    for key in sorted(counter, key=lambda k: (k != "punto", k)):
        print(f"  {key}: {counter[key]}")
    print(f"\nGuardadas en {RAW_DIR}")
