"""
Extracción compartida entre golden_capture.py y golden_check.py: lee TODO
lo que nos importa validar de una captura (header + las 10 filas con
héroe/ítems/stats/nombre). A propósito es de solo lectura -- a diferencia
de procesar.py no toca la base, no mueve archivos ni guarda nada en
data/review/, para poder correrlo las veces que haga falta sin efectos
secundarios ni ensuciar la cola de revisión real.

Capturar y chequear DEBEN medir exactamente lo mismo, por eso viven en un
solo lugar en vez de duplicar la lógica en los dos scripts.
"""
import cv2

import icon_recognition as ic
import layout
import ocr_extraction as ocr


def _identificar_iconos_fila(image, row_index: int, side: str) -> dict:
    boxes = layout.get_row_boxes(row_index, side)
    hero_name, _, _, _, _ = ic.identificar_heroe(image, boxes["portrait"])
    items = []
    for item_box in boxes["items"]:
        name, _, _, _, _ = ic.identificar_item(image, item_box)
        items.append(None if name == "unknown" else name)
    return {"heroe": None if hero_name == "unknown" else hero_name, "items": items}


def extraer_captura_completa(path: str, username: str) -> dict:
    raw = cv2.imread(path)
    if raw is None:
        raise ValueError(f"No se pudo abrir la imagen: {path}")
    image = layout.normalize_to_ref_width(raw)

    partida = ocr.extraer_partida(path, username)

    resultado = {
        "header": partida["header"],
        "my_side": partida["my_side"],
        "my_row_index": partida["my_row_index"],
        "rows_blue": [],
        "rows_red": [],
    }
    for row_index in range(layout.NUM_ROWS):
        for side, key in (("blue", "rows_blue"), ("red", "rows_red")):
            row_data = dict(partida[key][row_index])
            row_data.update(_identificar_iconos_fila(image, row_index, side))
            resultado[key].append(row_data)
    return resultado
