"""
Fase 3: corre el reconocimiento de íconos (héroes + ítems) sobre
data/samples/, usando el layout de la Fase 2 para ubicar cada recorte y
icon_recognition.py para identificarlo contra la base de referencia.

Los casos por debajo del umbral de confianza quedan marcados "unknown" y el
recorte se guarda en data/review/ junto con sus 3 candidatos más cercanos
(codificados en el nombre de archivo), para que revisarlos a mano sea elegir
de una lista corta en vez de adivinar entre ~130 opciones.

Uso: python src/recognize_icons.py
"""
import glob
from pathlib import Path

import cv2

import layout
import icon_recognition as ic

ROOT = Path(__file__).resolve().parent.parent


def process_sample(path: str) -> dict:
    raw = cv2.imread(path)
    image = layout.normalize_to_ref_width(raw)
    sample_name = Path(path).stem

    stats = {"heroes_ok": 0, "heroes_unknown": 0, "items_ok": 0, "items_unknown": 0}

    print(f"\n{'='*70}\n{path}\n{'='*70}")
    for row_idx in range(layout.NUM_ROWS):
        for side in ["blue", "red"]:
            boxes = layout.get_row_boxes(row_idx, side)

            name, dist, conf, crop, top3 = ic.identificar_heroe(image, boxes["portrait"])
            if name == "unknown":
                stats["heroes_unknown"] += 1
                etiqueta = f"{sample_name}_row{row_idx}_{side}_hero"
                ic.guardar_para_revision(crop, etiqueta, top3)
            else:
                stats["heroes_ok"] += 1
            print(f"  Fila {row_idx+1} {side.upper():4} hero={name:16} dist={dist} conf={conf:.2f}")

            item_names = []
            for slot_idx, item_box in enumerate(boxes["items"]):
                iname, idist, iconf, icrop, itop3 = ic.identificar_item(image, item_box)
                if iname == "unknown":
                    stats["items_unknown"] += 1
                    etiqueta = f"{sample_name}_row{row_idx}_{side}_item{slot_idx}"
                    ic.guardar_para_revision(icrop, etiqueta, itop3)
                else:
                    stats["items_ok"] += 1
                item_names.append(f"{iname}({idist})")
            print(f"      items: {', '.join(item_names)}")

    return stats


if __name__ == "__main__":
    samples = sorted(glob.glob(str(ROOT / "data" / "samples" / "*")))
    if not samples:
        print("No hay capturas en data/samples/")

    total = {"heroes_ok": 0, "heroes_unknown": 0, "items_ok": 0, "items_unknown": 0}
    for path in samples:
        stats = process_sample(path)
        for k in total:
            total[k] += stats[k]

    print(f"\n{'='*70}\nRESUMEN\n{'='*70}")
    h_total = total["heroes_ok"] + total["heroes_unknown"]
    i_total = total["items_ok"] + total["items_unknown"]
    if h_total:
        print(f"Héroes: {total['heroes_ok']}/{h_total} identificados ({100*total['heroes_ok']/h_total:.0f}%), {total['heroes_unknown']} unknown")
    if i_total:
        print(f"Ítems:  {total['items_ok']}/{i_total} identificados ({100*total['items_ok']/i_total:.0f}%), {total['items_unknown']} unknown")
    print(f"Revisar casos dudosos en: data/review/")
