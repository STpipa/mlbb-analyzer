"""
Revisión manual de los recortes dudosos guardados en data/review/ por
recognize_icons.py. Cada corrección confirmada acá se suma a la "base
aprendida" (data/reference/heroes_learned/ o items_learned/): un recorte
real de tu propia partida, no arte de wiki. Con más confirmaciones, el
matching futuro debería mejorar, porque va a poder comparar contra recortes
del mismo origen (capturas reales) en vez de solo contra íconos promocionales.

Uso: python src/revisar_iconos.py
Por cada caso: abre la imagen con el visor de Windows y pregunta cuál es la
respuesta correcta. Podés:
  - escribir 1, 2 o 3 para elegir uno de los candidatos sugeridos
  - escribir el nombre exacto si ninguno de los 3 es correcto
  - escribir 's' para saltear (se revisa otro día)
  - escribir 'd' para descartar (no es útil, ej. un slot de ítem vacío)
  - escribir 'q' para cortar la sesión acá
"""
import os
import shutil
from pathlib import Path

import icon_recognition as ic

ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = ROOT / "data" / "review"


def parse_filename(path: Path):
    stem = path.stem
    if "__" in stem:
        etiqueta, cand_part = stem.split("__", 1)
    else:
        etiqueta, cand_part = stem, ""

    candidates = []
    if cand_part:
        for token in cand_part.split("+"):
            if "-" in token:
                name, dist = token.rsplit("-", 1)
                candidates.append((name, dist))

    tipo = "hero" if "_hero" in etiqueta else ("item" if "_item" in etiqueta else "?")
    return etiqueta, tipo, candidates


def valid_names(tipo: str) -> set:
    if tipo == "hero":
        return {name for name, _ in ic.get_hero_hashes()}
    return {name for name, _ in ic.get_item_hashes()}


def review_one(path: Path) -> str:
    etiqueta, tipo, candidates = parse_filename(path)
    print(f"\n{'-'*60}\n{path.name}")
    print(f"Tipo: {'héroe' if tipo == 'hero' else 'ítem' if tipo == 'item' else 'desconocido'}")
    for i, (name, dist) in enumerate(candidates, start=1):
        print(f"  {i}) {name} (distancia={dist})")

    try:
        os.startfile(str(path))
    except Exception:
        print(f"(No se pudo abrir automático, abrilo a mano: {path})")

    names_ok = valid_names(tipo) if tipo in ("hero", "item") else set()

    while True:
        answer = input("Respuesta [1/2/3 / nombre / s=saltar / d=descartar / q=salir]: ").strip()
        if answer.lower() == "q":
            return "quit"
        if answer.lower() == "s":
            return "skip"
        if answer.lower() == "d":
            path.unlink()
            print("Descartado.")
            return "discarded"
        if answer in ("1", "2", "3"):
            idx = int(answer) - 1
            if idx < len(candidates):
                return confirm(path, etiqueta, tipo, candidates[idx][0])
            print("Ese número no tiene candidato.")
            continue
        # nombre libre
        if names_ok and answer not in names_ok:
            confirm_anyway = input(
                f"'{answer}' no está en la base de referencia actual. ¿Seguro? [s/N]: "
            ).strip().lower()
            if confirm_anyway != "s":
                continue
        return confirm(path, etiqueta, tipo, answer)


def confirm(path: Path, etiqueta: str, tipo: str, name: str) -> str:
    dest_dir = ic.HERO_LEARNED_DIR if tipo == "hero" else ic.ITEM_LEARNED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}__{etiqueta}.png"
    shutil.copy(path, dest)
    path.unlink()
    print(f"Confirmado como '{name}'. Guardado en {dest.relative_to(ROOT)}")
    return "confirmed"


if __name__ == "__main__":
    files = sorted(REVIEW_DIR.glob("*.png"))
    if not files:
        print("No hay nada para revisar en data/review/.")
        raise SystemExit

    print(f"{len(files)} casos para revisar.")
    confirmed = 0
    for path in files:
        if not path.exists():
            continue
        result = review_one(path)
        if result == "quit":
            break
        if result == "confirmed":
            confirmed += 1

    print(f"\nListo por ahora. Confirmados: {confirmed}.")
    if confirmed:
        ic.reload_hashes()
        print("Base aprendida actualizada para la próxima corrida de recognize_icons.py.")
