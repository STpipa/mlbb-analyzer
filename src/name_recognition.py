"""
Fase 4c: lectura del nombre de jugador con un motor de OCR más robusto que
Tesseract. A diferencia de los dígitos (10 símbolos posibles, resuelto con
plantillas propias en digit_recognition.py) un nombre de MLBB es texto
libre — letras, símbolos de clan, tipografías estilizadas ("F.A) -GaZze-",
"®", etc.) — así que hace falta un motor de reconocimiento general más
fuerte que Tesseract en vez de plantillas fijas. EasyOCR (basado en deep
learning) tiende a manejar mejor ese ruido visual.

El modelo se carga una sola vez (lazy, primera llamada) porque tarda unos
segundos y baja los pesos la primera vez que se usa en la máquina.
"""
import cv2

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["es", "en"], gpu=False, verbose=False)
    return _reader


def leer_nombre(crop_bgr) -> tuple[str, float]:
    """Lee el recorte de nombre (imagen cruda, sin binarizar — EasyOCR
    aprovecha mejor el detalle de escala de grises que Tesseract). Devuelve
    (texto, confianza); confianza 0.0 si no detectó nada."""
    if crop_bgr is None or crop_bgr.size == 0:
        return "", 0.0
    ampliado = cv2.resize(crop_bgr, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    resultados = _get_reader().readtext(ampliado, detail=1, paragraph=False)
    if not resultados:
        return "", 0.0
    resultados.sort(key=lambda r: r[0][0][0])  # de izquierda a derecha, por x del cuadro
    texto = " ".join(r[1] for r in resultados)
    confianza = min(r[2] for r in resultados)
    return texto, confianza
