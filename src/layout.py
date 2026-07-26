"""
Fase 2: layout calibrado de la pantalla de post-partida de MLBB.

Estrategia de normalización: en vez de forzar cada captura a una resolución
fija (ancho x alto), reescalamos SOLO por ancho (preservando el aspect ratio
original) hasta REF_WIDTH. Esto se debe a que, comparando las 5 capturas de
muestra, el contenido del marcador y las 10 filas de jugadores tiene EXACTAMENTE
los mismos píxeles en todas ellas (mismo ancho nativo 1366) — la única
diferencia de alto entre capturas viene de contenido extra al pie (los botones
"Datos"/"Salir", presentes en algunas capturas y recortados en otras), no de
un verdadero cambio de escala. Forzar una altura fija habría deformado el
contenido real. Todas las coordenadas de abajo están definidas en el sistema
de referencia post-normalización (ancho = REF_WIDTH), medidas a mano sobre
data/samples/Captura3.PNG con grillas de precisión.

Si en el futuro aparecen capturas de un dispositivo con una relación de
aspecto genuinamente distinta (no solo contenido extra recortado), estas
constantes van a necesitar un segundo perfil de calibración.
"""
from dataclasses import dataclass

import cv2
import numpy as np

REF_WIDTH = 1366

NUM_ROWS = 5

# Top de cada una de las 5 filas de jugadores. NO son perfectamente equidistantes
# (se midió con un perfil de energía de bordes por fila sobre 3 capturas de
# muestra distintas y salió consistente entre ellas, con un paso real de
# ~97-99px en vez de un promedio ingenuo de 103.6px que arrastraba error
# acumulado fila a fila y terminaba recortando los dígitos de K/D/A en las
# filas 3 y 4).
ROW_TOPS = [160, 258, 355, 454, 553]

# --- Header (marcador / timer) ---
SCORE_LEFT_BOX = (380, 25, 465, 100)
SCORE_RIGHT_BOX = (895, 25, 972, 100)
RESULT_TEXT_BOX = (525, 15, 855, 100)   # "VICTORY" / "DEFEAT"
TIMER_BOX = (900, 90, 1150, 118)

# --- Columnas lado azul (izquierda), offsets relativos al top de cada fila ---
BLUE = {
    "heart": (75, 29, 115, 69),
    # el box de retrato original (148,4,230,76) incluye demasiado fondo y
    # pisa la bandera/nivel en las esquinas, lo cual arruina el perceptual
    # hash (Fase 3) porque los íconos de referencia vienen recortados bien
    # ajustados a la cara. Este es un recorte más chico, centrado en el
    # círculo real del retrato, sin tocar bandera/nivel.
    "portrait": (155, 0, 232, 77),
    "level": (148, 74, 192, 96),
    "flag": (153, 4, 187, 26),
    # arranca en 263 y no en el borde del retrato (232) porque entre medio
    # hay un ícono cuadrado (género/rol) que Tesseract confunde con letras
    # sueltas ("m", "ma.", "pan~", etc.) pegadas al nombre real.
    "name": (263, 14, 402, 41),
    # K, D, A y oro NO son columnas de ancho fijo (el juego los separa por
    # espacios, así que la posición de cada número se corre según cuántos
    # dígitos tienen los anteriores). En vez de perseguir 4 cajas angostas
    # que se desalinean fila a fila, se recorta el renglón completo de stats
    # como un solo bloque de texto "K D A Gold" y se separa por espacios en
    # el post-procesamiento (ver calibrate.py).
    "stats": (403, 14, 592, 41),
    # medalla de rating (plateada) o corona MVP (dorada) — la corona MVP es
    # más alta que la medalla normal, por eso el ícono usa una franja más
    # generosa; el número de rating se recorta aparte, bien angosto, porque
    # si se mezcla con el gráfico del ícono el threshold se arruina y el OCR
    # falla.
    "badge_icon": (590, 15, 656, 58),
    "badge_number": (590, 58, 656, 90),
    # el paso real entre íconos es ~49px, no ~40px como asumía la calibración
    # original — se midió detectando los círculos de los íconos con
    # HoughCircles sobre decenas de filas reales. Con el paso viejo, las
    # cajas de los slots 4/5/6 quedaban cada vez más corridas y terminaban
    # agarrando mitad de un ícono + mitad del siguiente, lo cual el
    # reconocimiento de íconos interpretaba como "el mismo ítem repetido".
    "items": [
        (241, 49, 281, 89),
        (290, 49, 330, 89),
        (339, 49, 379, 89),
        (388, 49, 428, 89),
        (437, 49, 477, 89),
        (486, 49, 526, 89),
    ],
}

# --- Columnas lado rojo (derecha) ---
RED = {
    "badge_icon": (718, 15, 774, 58),
    "badge_number": (718, 58, 774, 90),
    # ídem lado azul: "Gold K D A" recortado como un solo bloque de texto.
    "stats": (774, 14, 968, 41),
    # el nombre en el lado rojo está alineado contra el retrato (a la derecha),
    # así que arranca en distinta posición según su largo: la caja cubre todo
    # el hueco entre las stats y el retrato en vez de asumir un punto fijo.
    "name": (870, 14, 1145, 41),
    # ídem lado azul: paso real ~48px, recalibrado con HoughCircles.
    "items": [
        (834, 49, 874, 89),
        (882, 49, 922, 89),
        (930, 49, 970, 89),
        (978, 49, 1018, 89),
        (1026, 49, 1066, 89),
        (1074, 49, 1114, 89),
    ],
    "flag": (1191, 4, 1222, 26),
    "portrait": (1148, 4, 1228, 76),
    "level": (1150, 74, 1196, 96),
    "heart": (1250, 29, 1292, 69),
}


@dataclass
class RowBoxes:
    side: str
    row_index: int
    boxes: dict


def normalize_to_ref_width(image: np.ndarray) -> np.ndarray:
    """Reescala una captura (array BGR de OpenCV) a ancho=REF_WIDTH preservando
    el aspect ratio original (ver docstring del módulo)."""
    h, w = image.shape[:2]
    scale = REF_WIDTH / w
    new_h = round(h * scale)
    return cv2.resize(image, (REF_WIDTH, new_h), interpolation=cv2.INTER_AREA)


def row_top(row_index: int) -> float:
    return ROW_TOPS[row_index]


def _offset_box(box, row_index: int):
    x1, y1, x2, y2 = box
    top = row_top(row_index)
    return (x1, round(top + y1), x2, round(top + y2))


def get_row_boxes(row_index: int, side: str) -> dict:
    """side: 'blue' o 'red'. Devuelve un dict de nombre_de_campo -> (x1,y1,x2,y2)
    en píxeles absolutos sobre la imagen normalizada a REF_WIDTH."""
    template = BLUE if side == "blue" else RED
    boxes = {}
    for key, val in template.items():
        if key == "items":
            boxes["items"] = [_offset_box(b, row_index) for b in val]
        else:
            boxes[key] = _offset_box(val, row_index)
    return boxes


def crop(image: np.ndarray, box) -> np.ndarray:
    x1, y1, x2, y2 = [max(0, round(v)) for v in box]
    h, w = image.shape[:2]
    x2, y2 = min(w, x2), min(h, y2)
    return image[y1:y2, x1:x2]
