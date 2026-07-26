"""
Uso diario: procesa las capturas nuevas en data/screenshots/, extrae todo
(marcador, timer, K/D/A/oro/rating/MVP por OCR + héroe/ítems por perceptual
hashing) y lo agrega a la base SQLite (data/db/mlbb.db). Las capturas ya
procesadas se mueven a data/screenshots/procesadas/ para no repetirlas.

Uso: python src/procesar.py
"""
import glob
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import cv2

import layout
import ocr_extraction as ocr
import icon_recognition as ic
import database as db

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = ROOT / "data" / "screenshots"
PROCESSED_DIR = SCREENSHOTS_DIR / "procesadas"


def _to_int(txt):
    try:
        return int(txt)
    except (TypeError, ValueError):
        return None


def _to_float(txt):
    try:
        return float(txt)
    except (TypeError, ValueError):
        return None


def build_player_row(row_data: dict, hero_name: str, item_names: list, lado: str) -> dict:
    items = (item_names + [None] * 6)[:6]
    return {
        "lado": lado,
        "jugador": row_data["name"] or None,
        "heroe": hero_name,
        "item_1": items[0],
        "item_2": items[1],
        "item_3": items[2],
        "item_4": items[3],
        "item_5": items[4],
        "item_6": items[5],
        "kills": _to_int(row_data["kills"]),
        "deaths": _to_int(row_data["deaths"]),
        "assists": _to_int(row_data["assists"]),
        "oro": _to_int(row_data["gold"]),
        "rating": _to_float(row_data["rating"]),
        "mvp_flag": int(bool(row_data["mvp"])),
    }


def identify_icons_for_row(image, row_index: int, side: str, screenshot_stem: str):
    boxes = layout.get_row_boxes(row_index, side)
    prefix = f"{screenshot_stem}_row{row_index}_{side}"
    hero_name, _, _, hero_crop, hero_top3 = ic.identificar_heroe(image, boxes["portrait"])
    if hero_name == "unknown":
        ic.guardar_para_revision(hero_crop, f"{prefix}_hero", hero_top3)

    item_names = []
    for slot_idx, item_box in enumerate(boxes["items"]):
        name, _, _, crop, top3 = ic.identificar_item(image, item_box)
        if name == "unknown":
            ic.guardar_para_revision(crop, f"{prefix}_item{slot_idx}", top3)
            item_names.append(None)
        else:
            item_names.append(name)
    return hero_name if hero_name != "unknown" else None, item_names


def process_screenshot(path: Path, username: str, usuario_id: int, conn) -> int | None:
    """Procesa una captura y la archiva en procesadas/ si se cargó bien.
    Devuelve el match_id nuevo, o None si se saltó (duplicada) o falló."""
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if db.screenshot_hash_already_processed(conn, content_hash, usuario_id):
        print(f"  (ya la habías procesado antes, se salta) {path.name}")
        return None

    raw = cv2.imread(str(path))
    if raw is None:
        print(f"  ERROR: no se pudo abrir {path.name}")
        return None
    image = layout.normalize_to_ref_width(raw)

    partida = ocr.extraer_partida(str(path), username)
    header = partida["header"]
    my_side = partida["my_side"]
    my_row_index = partida["my_row_index"]

    score_blue = _to_int(header["score_left"])
    score_red = _to_int(header["score_right"])
    marcador_propio = score_blue if my_side == "blue" else score_red
    marcador_enemigo = score_red if my_side == "blue" else score_blue

    fecha = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    # El nombre de captura no es confiable como identificador: la app de
    # capturas reutiliza nombres como "Captura.PNG" para fotos distintas, y
    # ahora que hay multi-usuario dos cuentas distintas podrían llegar a
    # subir el mismo archivo (ej. compañeros de la misma partida). Se
    # archiva con el hash de contenido + el usuario en el nombre para que
    # nunca se pise un archivo ya guardado.
    archive_name = f"{path.stem}__u{usuario_id}__{content_hash[:8]}{path.suffix}"

    match_row = {
        "usuario_id": usuario_id,
        "fecha": fecha,
        "duracion": header["timer"] or None,
        "resultado": (header["result"] or "").upper() or None,
        "marcador_propio": marcador_propio,
        "marcador_enemigo": marcador_enemigo,
        "screenshot": archive_name,
        "content_hash": content_hash,
    }
    match_id = db.insert_match(conn, match_row)

    for row_index in range(layout.NUM_ROWS):
        for side in ("blue", "red"):
            hero_name, item_names = identify_icons_for_row(image, row_index, side, path.stem)
            row_data = partida["rows_blue"][row_index] if side == "blue" else partida["rows_red"][row_index]
            if side != my_side:
                lado = "rival"
            elif row_index == my_row_index:
                lado = "yo"
            else:
                lado = "aliado"
            player_row = build_player_row(row_data, hero_name, item_names, lado)
            db.insert_player(conn, match_id, player_row)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(PROCESSED_DIR / archive_name))

    print(f"  OK: {path.name} -> match_id={match_id} ({match_row['resultado']}, {marcador_propio}-{marcador_enemigo})")
    return match_id


if __name__ == "__main__":
    username = ocr.load_username()
    conn = db.get_connection()
    db.init_db(conn)
    usuario_id = db.get_or_create_user(conn, username)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    screenshots = sorted(
        p for p in Path(SCREENSHOTS_DIR).glob("*")
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
    if not screenshots:
        print("No hay capturas nuevas en data/screenshots/")

    procesadas = 0
    for path in screenshots:
        print(f"Procesando {path.name}...")
        try:
            match_id = process_screenshot(path, username, usuario_id, conn)
        except Exception as e:
            print(f"  ERROR procesando {path.name}: {e}")
            continue
        if match_id:
            procesadas += 1

    conn.close()
    pendientes = len(list(ic.REVIEW_DIR.glob("*.png")))
    print(f"\nListo. {procesadas} captura(s) nueva(s) agregada(s) a la base.")
    print(f"Casos dudosos de héroes/ítems pendientes de revisión: {pendientes} (en data/review/).")
