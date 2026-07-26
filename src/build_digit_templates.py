"""
Arma una plantilla promedio por dígito a partir de las muestras minadas en
data/reference/digits_raw/ (ver mine_digit_templates.py). Correr de nuevo
cada vez que se agreguen más muestras confirmadas al corpus.

Uso: python src/build_digit_templates.py
"""
import glob
from pathlib import Path

import cv2
import numpy as np

import digit_recognition as dr

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "reference" / "digits_raw"
OUT_DIR = ROOT / "data" / "reference" / "digit_templates"


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for digit_dir in sorted(RAW_DIR.iterdir()):
        if not digit_dir.is_dir():
            continue
        files = glob.glob(str(digit_dir / "*.png"))
        if not files:
            continue
        alto, ancho = dr.CANON_SIZE[1], dr.CANON_SIZE[0]
        acc = np.zeros((alto, ancho), dtype=np.float64)
        n = 0
        for f in files:
            img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            acc += dr._canon(img).astype(np.float64)
            n += 1
        if n == 0:
            continue
        template = (acc / n).astype(np.uint8)
        cv2.imwrite(str(OUT_DIR / f"{digit_dir.name}.png"), template)
        print(f"  {digit_dir.name}: promedio de {n} muestras")


if __name__ == "__main__":
    print("Armando plantillas por dígito...")
    build()
    print(f"\nGuardadas en {OUT_DIR}")
