"""
Chequeo de integridad de los corpus "aprendidos" (data/reference/heroes_learned/
y items_learned/) contra la lista real de héroes/ítems de la wiki.

Nace del bug encontrado el 2026-07-26: 5 archivos con la etiqueta de
revisión y el nombre confirmado en el orden equivocado dentro del nombre de
archivo, y 29 recortes de héroe guardados por error en la carpeta de
ítems -- ambos casos contaminan silenciosamente el reconocimiento (un
nombre que no es un héroe/ítem real termina "ganando" el matching de algún
recorte) sin que nada avise, hasta que alguien nota un dato imposible en la
base a mano. Este script detecta esa misma clase de problema antes de que
llegue a contaminar una partida.

Correr esto:
  - antes de un reproceso grande,
  - después de una tanda de revisar_iconos.py,
  - si algo empieza a reconocerse raro sin razón aparente.

Uso: python src/validar_corpus.py
Código de salida: 0 si no hay problemas, 1 si hay algo para corregir.
"""
import sys
from pathlib import Path

import icon_recognition as ic


def _nombres_wiki(carpeta: Path) -> set:
    return {p.stem for p in carpeta.glob("*.png")}


def _revisar(carpeta_aprendida: Path, nombres_propios: set, nombres_otra_categoria: set,
             categoria: str, otra_categoria: str) -> list:
    problemas = []
    if not carpeta_aprendida.exists():
        return problemas
    for path in sorted(carpeta_aprendida.glob("*.png")):
        nombre = path.stem.split("__")[0]
        if not nombre:
            problemas.append((path.name, "nombre vacío -- revisar el formato del archivo (falta <Nombre> antes del primer '__')"))
        elif nombre in nombres_otra_categoria and nombre not in nombres_propios:
            problemas.append((path.name, f"'{nombre}' es un {otra_categoria}, no un {categoria} -- archivo en la carpeta equivocada"))
        elif nombre not in nombres_propios:
            problemas.append((path.name, f"'{nombre}' no está en la lista de {categoria}s de la wiki (¿typo? ¿etiqueta/nombre en el orden equivocado?)"))
    return problemas


def verificar() -> tuple:
    """(problemas_heroes, problemas_items), cada una lista de (archivo,
    motivo). Ambas vacías = todo OK."""
    heroes_wiki = _nombres_wiki(ic.HERO_REF_DIR)
    items_wiki = _nombres_wiki(ic.ITEM_REF_DIR)
    problemas_heroes = _revisar(ic.HERO_LEARNED_DIR, heroes_wiki, items_wiki, "héroe", "ítem")
    problemas_items = _revisar(ic.ITEM_LEARNED_DIR, items_wiki, heroes_wiki, "ítem", "héroe")
    return problemas_heroes, problemas_items


def main():
    problemas_heroes, problemas_items = verificar()

    if problemas_heroes:
        print(f"\ndata/reference/heroes_learned/ -- {len(problemas_heroes)} problema(s):")
        for archivo, motivo in problemas_heroes:
            print(f"  {archivo}: {motivo}")
    if problemas_items:
        print(f"\ndata/reference/items_learned/ -- {len(problemas_items)} problema(s):")
        for archivo, motivo in problemas_items:
            print(f"  {archivo}: {motivo}")

    total = len(problemas_heroes) + len(problemas_items)
    if total == 0:
        print("OK: los dos corpus aprendidos coinciden con la lista de la wiki, sin nombres raros ni carpetas cruzadas.")
    else:
        print(f"\n{total} problema(s) encontrados. Corregir el nombre/carpeta del archivo y correr de nuevo antes de reprocesar.")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
