"""
Congela el resultado ACTUAL del pipeline sobre el set de capturas de
referencia (data/golden/*.png) como la respuesta "correcta" contra la que
golden_check.py va a comparar de acá en adelante.

IMPORTANTE: correr esto solo después de confirmar (a ojo contra la captura
real, o porque ya se revisó a mano en otro lado) que el resultado actual es
efectivamente correcto. Si se corre con un bug activo, ese bug queda
"congelado" como si fuera el comportamiento esperado — no reemplaza la
revisión humana, solo evita que un cambio futuro lo rompa sin que nadie se
entere.

Uso: python src/golden_capture.py
"""
import json
from pathlib import Path

import golden_common as gc
import ocr_extraction as ocr

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = ROOT / "data" / "golden"
BASELINE_PATH = GOLDEN_DIR / "baseline.json"


def main():
    username = ocr.load_username()
    files = sorted(
        p for p in GOLDEN_DIR.glob("*")
        if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
    if not files:
        print(f"No hay capturas en {GOLDEN_DIR}. Copiá ahí las capturas de referencia primero.")
        return

    baseline = {}
    for path in files:
        print(f"Capturando {path.name}...")
        baseline[path.name] = gc.extraer_captura_completa(str(path), username)

    BASELINE_PATH.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nListo. Referencia guardada para {len(files)} captura(s) en {BASELINE_PATH}.")


if __name__ == "__main__":
    main()
