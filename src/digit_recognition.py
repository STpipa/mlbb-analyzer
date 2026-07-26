"""
Fase 4b: reconocimiento de dígitos aislados por comparación de plantillas,
pensado como reemplazo de Tesseract para los campos numéricos (rating,
K/D/A, oro, marcador). Mismo enfoque que icon_recognition.py: en vez de un
motor de OCR genérico, se compara el recorte de UN solo carácter contra una
plantilla promedio armada con muestras reales confirmadas (ver
mine_digit_templates.py + build_digit_templates.py). La tipografía del
juego es siempre la misma y las muestras ya llegan alineadas/recortadas por
componentes conexas, así que un promedio simple alcanza — no hace falta
nada más sofisticado, y es mucho más confiable que Tesseract, que confunde
puntualmente algunos glifos de esta fuente (ej. "7" leído como "1").
"""
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "data" / "reference" / "digit_templates"
CANON_SIZE = (48, 64)  # (ancho, alto)

# Umbrales de aceptación: si el mejor candidato no supera esto, o si el
# segundo candidato le pisa los talones, se prefiere "no reconocido" antes
# que arriesgar una lectura dudosa (misma filosofía que HERO_THRESHOLD /
# ITEM_THRESHOLD en icon_recognition.py).
MATCH_THRESHOLD = 0.80
MARGIN_THRESHOLD = 0.03

_templates: dict[str, np.ndarray] | None = None


def _canon(img_gray) -> np.ndarray:
    return cv2.resize(img_gray, CANON_SIZE, interpolation=cv2.INTER_AREA)


def _load_templates() -> dict[str, np.ndarray]:
    global _templates
    if _templates is not None:
        return _templates
    templates = {}
    if TEMPLATES_DIR.exists():
        for path in sorted(TEMPLATES_DIR.glob("*.png")):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                templates[path.stem] = img
    _templates = templates
    return templates


def es_punto_decimal(w: int, h: int, area: int, area_mediana: float) -> bool:
    """El punto decimal es un blob chico y aproximadamente cuadrado; los
    dígitos reales son bastante más altos que anchos y de área mayor. Se
    distingue por tamaño relativo al resto de los componentes del mismo
    número, no por plantilla (no hay muestras minadas de puntos sueltos,
    ver mine_digit_templates.py)."""
    return area_mediana > 0 and area < area_mediana * 0.35 and w <= h * 1.4


def identificar_digito(crop_gray) -> str | None:
    """Compara un recorte YA aislado (un solo dígito, sobre fondo negro)
    contra las plantillas promedio. Devuelve el dígito como string, o None
    si ningún candidato es suficientemente confiable — mejor no adivinar."""
    templates = _load_templates()
    if not templates or crop_gray is None or crop_gray.size == 0:
        return None
    probe = _canon(crop_gray).astype(np.float64) / 255.0
    scores = []
    for digito, template in templates.items():
        t = template.astype(np.float64) / 255.0
        score = 1.0 - np.abs(probe - t).mean()
        scores.append((score, digito))
    scores.sort(reverse=True)
    best_score, best_digito = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    if best_score < MATCH_THRESHOLD or (best_score - second_score) < MARGIN_THRESHOLD:
        return None
    return best_digito
