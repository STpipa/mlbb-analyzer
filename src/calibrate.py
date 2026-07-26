"""
Fase 2/4: corre la extracción de OCR (ocr_extraction.py) sobre data/samples/
e imprime marcador, timer, y el texto de cada fila (nombre/K/D/A/oro/rating)
para verificar a ojo que las coordenadas del layout y el OCR están bien.

Uso: python src/calibrate.py
"""
import glob
from pathlib import Path

import ocr_extraction as ocr

ROOT = Path(__file__).resolve().parent.parent


def print_sample(path: str, username: str) -> None:
    print(f"\n{'='*70}\n{path}\n{'='*70}")
    try:
        partida = ocr.extraer_partida(path, username)
    except ValueError as e:
        print(f"  ERROR: {e}")
        return

    h = partida["header"]
    print(f"Marcador: {h['score_left']} - {h['score_right']}  |  Resultado: {h['result']}  |  Timer: {h['timer']}")
    print(f"Lado detectado como 'yo' (username='{username}'): {partida['my_side']} fila {partida['my_row_index'] + 1}")

    rows_blue, rows_red = partida["rows_blue"], partida["rows_red"]
    my_side = partida["my_side"]
    my_row_index = partida["my_row_index"]
    for i, (b, r) in enumerate(zip(rows_blue, rows_red)):
        b_tag = ("yo" if i == my_row_index else "aliado") if my_side == "blue" else "rival"
        r_tag = ("yo" if i == my_row_index else "aliado") if my_side == "red" else "rival"
        print(f"  Fila {i+1} [{b_tag:5}] AZUL  name={b['name']!r:22} K={b['kills']:>3} D={b['deaths']:>3} A={b['assists']:>3} gold={b['gold']:>6} rating={b['rating']:>5} mvp={b['mvp']}")
        print(f"  Fila {i+1} [{r_tag:5}] ROJO  name={r['name']!r:22} K={r['kills']:>3} D={r['deaths']:>3} A={r['assists']:>3} gold={r['gold']:>6} rating={r['rating']:>5} mvp={r['mvp']}")


if __name__ == "__main__":
    username = ocr.load_username()
    samples = sorted(glob.glob(str(ROOT / "data" / "samples" / "*")))
    if not samples:
        print("No hay capturas en data/samples/")
    for path in samples:
        print_sample(path, username)
