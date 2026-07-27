"""
Fase 3: reconocimiento de íconos (héroes e ítems) contra la base de
referencia armada en la Fase 1, usando perceptual hashing (imagehash.phash)
y distancia de Hamming.

Nota de calibración: phash es MUY sensible a corrimientos de pocos píxeles
entre el recorte y la referencia (se probó a mano: un corrimiento de apenas
5px ya sube la distancia de 0 a 12 sobre 64). Como el recorte en juego y el
ícono de la wiki nunca van a estar perfectamente alineados (distinto zoom/
encuadre de origen, arte promocional 2D vs. render del motor del juego),
identificar_icono no compara un único recorte fijo: prueba una pequeña
grilla de variantes (corridas en x/y y algo de escala) alrededor de la caja
nominal y se queda con la mejor distancia encontrada.

Aun así, comparando contra las capturas de muestra, la distancia a la
referencia de wiki CORRECTA cae en el mismo rango que la de referencias
incorrectas (10-18) — no hay un umbral que separe limpio lo bueno de lo
malo. Por eso existe la "base aprendida" (ver más abajo): recortes reales
de tus propias capturas, confirmados a mano vía revisar_iconos.py, que se
suman como referencia adicional. Un recorte de tu juego real matchea mucho
mejor contra OTRO recorte de tu juego real que contra arte de wiki, así que
la precisión debería mejorar con el uso en vez de quedar fija.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import imagehash

ROOT = Path(__file__).resolve().parent.parent
HERO_REF_DIR = ROOT / "data" / "reference" / "heroes"
ITEM_REF_DIR = ROOT / "data" / "reference" / "items"
HERO_LEARNED_DIR = ROOT / "data" / "reference" / "heroes_learned"
ITEM_LEARNED_DIR = ROOT / "data" / "reference" / "items_learned"
REVIEW_DIR = ROOT / "data" / "review"

# Umbral DURO a propósito: al principio, mientras la base "aprendida" todavía
# no tiene recortes reales confirmados, es mejor que la mayoría de los casos
# queden "unknown" y se revisen a mano (ver revisar_iconos.py) a que se
# guarde un dato incorrecto sin que nadie se entere. A medida que se
# confirmen más recortes reales, la distancia a la referencia correcta va a
# bajar (menos que contra arte de wiki) y este umbral se puede subir.
HERO_THRESHOLD = 10
ITEM_THRESHOLD = 10

# Grilla de búsqueda de alineación: corrimientos en x/y (px, sobre la imagen
# normalizada a REF_WIDTH) y variaciones de escala del lado del recorte.
_OFFSETS = (-10, -5, 0, 5, 10)
_SCALE_DELTAS = (-10, 0)

_hero_hashes = None
_item_hashes = None


def _load_wiki_hashes(folder: Path) -> list:
    """Cada archivo es '<Nombre>.png' -> el nombre exacto es el nombre del
    héroe/ítem."""
    entries = []
    for path in sorted(folder.glob("*.png")):
        with Image.open(path) as img:
            entries.append((path.stem, imagehash.phash(img.convert("RGB"))))
    return entries


def _load_learned_hashes(folder: Path) -> list:
    """Cada archivo es '<Nombre>__<lo-que-sea>.png' (ver revisar_iconos.py) ->
    el nombre es la parte antes del primer '__'. Puede haber varios archivos
    para el mismo nombre (varias confirmaciones)."""
    entries = []
    if not folder.exists():
        return entries
    for path in sorted(folder.glob("*.png")):
        name = path.stem.split("__")[0]
        with Image.open(path) as img:
            entries.append((name, imagehash.phash(img.convert("RGB"))))
    return entries


def get_hero_hashes() -> list:
    global _hero_hashes
    if _hero_hashes is None:
        _hero_hashes = _load_wiki_hashes(HERO_REF_DIR) + _load_learned_hashes(HERO_LEARNED_DIR)
    return _hero_hashes


def get_item_hashes() -> list:
    global _item_hashes
    if _item_hashes is None:
        _item_hashes = _load_wiki_hashes(ITEM_REF_DIR) + _load_learned_hashes(ITEM_LEARNED_DIR)
    return _item_hashes


def reload_hashes() -> None:
    """Fuerza a releer las carpetas de referencia (wiki + aprendida) en la
    próxima llamada. Usar después de confirmar casos con revisar_iconos.py
    dentro de la misma sesión de Python."""
    global _hero_hashes, _item_hashes
    _hero_hashes = None
    _item_hashes = None


def _crop_variants(image, box):
    x1, y1, x2, y2 = box
    h, w = image.shape[:2]
    seen = set()
    for dx in _OFFSETS:
        for dy in _OFFSETS:
            for ds in _SCALE_DELTAS:
                nx1 = max(0, x1 + dx)
                ny1 = max(0, y1 + dy)
                nx2 = min(w, x2 + dx + ds)
                ny2 = min(h, y2 + dy + ds)
                if nx2 - nx1 < 15 or ny2 - ny1 < 15:
                    continue
                key = (nx1, ny1, nx2, ny2)
                if key in seen:
                    continue
                seen.add(key)
                yield image[ny1:ny2, nx1:nx2]


def identificar_icono(image, box, reference_hashes: list, threshold: int):
    """Busca la mejor coincidencia para el ícono ubicado en `box` (x1,y1,x2,y2,
    sobre la imagen normalizada a REF_WIDTH) contra `reference_hashes` (lista
    de (nombre, hash) — puede haber varias entradas con el mismo nombre),
    probando una grilla de recortes ligeramente movidos/escalados alrededor
    de esa caja (ver docstring del módulo).

    Devuelve (nombre, distancia, confianza, mejor_recorte, top3):
      - nombre: el ícono con menor distancia, o "unknown" si ni la mejor
        variante bajó del umbral (mejor un dato faltante que uno inventado).
      - distancia: distancia de Hamming de la mejor variante encontrada.
      - confianza: score 0-1 derivado de la distancia.
      - mejor_recorte: el recorte (de la grilla) que dio esa distancia.
      - top3: lista [(nombre, distancia), ...] con las 3 mejores coincidencias
        distintas en total (no solo la ganadora), para que si el caso queda
        en duda la revisión manual sea elegir de una lista corta en vez de
        adivinar entre ~130 opciones.
    """
    best_per_name = {}
    best_crop_per_name = {}
    for crop in _crop_variants(image, box):
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        crop_hash = imagehash.phash(Image.fromarray(rgb))
        for name, ref_hash in reference_hashes:
            dist = crop_hash - ref_hash
            if name not in best_per_name or dist < best_per_name[name]:
                best_per_name[name] = dist
                best_crop_per_name[name] = crop

    if not best_per_name:
        return "unknown", None, 0.0, None, []

    ranked = sorted(best_per_name.items(), key=lambda kv: kv[1])
    top3 = ranked[:3]
    best_name, best_dist = ranked[0]
    best_crop = best_crop_per_name[best_name]

    confianza = max(0.0, 1 - best_dist / 64)
    if best_dist > threshold:
        return "unknown", best_dist, confianza, best_crop, top3
    return best_name, best_dist, confianza, best_crop, top3


def identificar_heroe(image, box):
    return identificar_icono(image, box, get_hero_hashes(), HERO_THRESHOLD)


def identificar_item(image, box):
    return identificar_icono(image, box, get_item_hashes(), ITEM_THRESHOLD)


_review_hashes = None


def _get_review_hashes() -> dict:
    """Cachea el phash de cada recorte ya pendiente en data/review/, para
    poder chequear duplicados sin releer/rehashear todo el directorio en
    cada llamada de guardar_para_revision() dentro de la misma corrida."""
    global _review_hashes
    if _review_hashes is None:
        _review_hashes = {}
        if REVIEW_DIR.exists():
            for path in REVIEW_DIR.glob("*.png"):
                try:
                    with Image.open(path) as img:
                        _review_hashes[path] = imagehash.average_hash(img, hash_size=16)
                except Exception:
                    continue
    return _review_hashes


def guardar_para_revision(crop, etiqueta: str, top3=None) -> None:
    """Guarda un recorte no reconocido (o dudoso) en data/review/ con un
    nombre descriptivo. Si se pasan los top3 candidatos, quedan codificados
    en el nombre de archivo para que revisar_iconos.py los pueda ofrecer
    como opciones rápidas.

    Antes de guardar, chequea si ya hay un recorte pendiente con el mismo
    contenido de píxeles (mismo caso, de un reproceso anterior) y si lo hay
    no vuelve a guardarlo — el nombre de archivo incluye el match_id, que
    se reasigna en cada reproceso completo, así que sin este chequeo la
    cola de revisión se llenaba de copias exactas del mismo caso (~75% de
    los 284 casos vistos el 2026-07-26 eran justamente esto)."""
    if crop is None or crop.size == 0:
        return
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    nuevo_hash = imagehash.average_hash(Image.fromarray(rgb), hash_size=16)
    hashes = _get_review_hashes()
    if any(nuevo_hash - h == 0 for h in hashes.values()):
        return  # ya hay un caso pendiente idéntico, no duplicar

    suffix = ""
    if top3:
        # nombres separados por "+" (no "_", que ya aparece en varios nombres
        # de héroes/ítems; "|" no se puede usar, es inválido en nombres de
        # archivo de Windows) y "-{distancia}" al final, separado con rsplit
        # al parsear porque también hay nombres con guiones (ej. "Lapu-Lapu").
        parts = [f"{name}-{dist}" for name, dist in top3]
        suffix = "__" + "+".join(parts)
    dest = REVIEW_DIR / f"{etiqueta}{suffix}.png"
    cv2.imwrite(str(dest), crop)
    hashes[dest] = nuevo_hash
