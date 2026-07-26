"""
Chequeo de regresión: vuelve a correr el pipeline sobre data/golden/*.png y
compara contra data/golden/baseline.json (armado con golden_capture.py).

Correr esto ANTES y DESPUÉS de tocar layout.py, ocr_extraction.py,
icon_recognition.py, digit_recognition.py, name_recognition.py, o los
corpus de referencia (data/reference/) -- cualquier diferencia significa
que algo cambió (para bien o para mal) y hay que revisarla a mano antes de
confiar en el cambio. Si la diferencia es una mejora intencional, correr
golden_capture.py de nuevo para actualizar la referencia.

Uso: python src/golden_check.py
Código de salida: 0 si no hay diferencias, 1 si hay diferencias o falta la
referencia (útil si en algún momento esto se engancha a algo automático).
"""
import json
import sys
from pathlib import Path

import golden_common as gc
import ocr_extraction as ocr

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = ROOT / "data" / "golden"
BASELINE_PATH = GOLDEN_DIR / "baseline.json"


def _diffs(esperado, actual, prefix=""):
    diffs = []
    if isinstance(esperado, dict) and isinstance(actual, dict):
        for key in esperado.keys() | actual.keys():
            diffs.extend(_diffs(esperado.get(key), actual.get(key), f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(esperado, list) and isinstance(actual, list):
        for i, (e, a) in enumerate(zip(esperado, actual)):
            diffs.extend(_diffs(e, a, f"{prefix}[{i}]"))
        if len(esperado) != len(actual):
            diffs.append((prefix, esperado, actual))
    elif esperado != actual:
        diffs.append((prefix, esperado, actual))
    return diffs


def main():
    if not BASELINE_PATH.exists():
        print(f"No existe {BASELINE_PATH}. Corré primero: python src/golden_capture.py")
        sys.exit(1)

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    username = ocr.load_username()

    total_diffs = 0
    for nombre_archivo, esperado in baseline.items():
        path = GOLDEN_DIR / nombre_archivo
        if not path.exists():
            print(f"AVISO: falta la captura {nombre_archivo} (estaba en la referencia).")
            continue
        actual = gc.extraer_captura_completa(str(path), username)
        diffs = _diffs(esperado, actual)
        if diffs:
            print(f"\n{nombre_archivo}: {len(diffs)} diferencia(s)")
            for campo, e, a in diffs:
                print(f"  {campo}: esperado={e!r}  actual={a!r}")
            total_diffs += len(diffs)

    if total_diffs == 0:
        print(f"OK: sin diferencias contra la referencia ({len(baseline)} captura(s) chequeadas).")
    else:
        print(f"\n{total_diffs} diferencia(s) encontradas. Revisalas: ¿son una mejora o una regresión?")
        print("Si son una mejora intencional, correr golden_capture.py de nuevo para actualizar la referencia.")
    sys.exit(1 if total_diffs else 0)


if __name__ == "__main__":
    main()
