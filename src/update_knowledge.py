"""
Fase 7: descarga la "base de conocimiento" del juego (stats de ítems y
datos de héroes) desde mobile-legends.fandom.com, para que el motor de
análisis (analizar_partida.py) tenga con qué razonar además de tus
partidas jugadas.

A diferencia de update_reference.py (que baja íconos), este script lee el
infobox estructurado (portable-infobox) que cada página del wiki ya trae
con atributos data-source="..." — ahí está el bonus de stats, el pasivo,
precio y receta de cada ítem, y el rol/tipo de daño/lane de cada héroe.

Uso: python src/update_knowledge.py
"""
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

WIKI_API = "https://mobile-legends.fandom.com/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (mlbb-analyzer knowledge updater)"}

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
ITEMS_JSON = KNOWLEDGE_DIR / "items.json"
HEROES_JSON = KNOWLEDGE_DIR / "heroes.json"


def api_get(params: dict) -> dict:
    url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_page_html(page_title: str) -> str:
    data = api_get({"action": "parse", "page": page_title, "prop": "text", "format": "json"})
    return data["parse"]["text"]["*"]


def strip_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return text.strip()


def infobox_field(html: str, source: str) -> str:
    """Extrae el texto de un campo data-source="X" del portable-infobox
    (formato simple: título + valor). Si el campo no existe, string vacío."""
    pattern = (
        rf'data-source="{re.escape(source)}"[^>]*>.*?'
        rf'<div class="pi-data-value pi-font">(.*?)</div>\s*</div>'
    )
    m = re.search(pattern, html, re.DOTALL)
    return strip_tags(m.group(1)) if m else ""


def infobox_price_field(html: str, source: str) -> str:
    """Precio/venta no vienen en un <div data-source=...> como el resto
    del infobox: son celdas <td data-source="..."> de una tabla, con el
    número envuelto en un <span style="color:gold">. Se toma la PRIMERA
    aparición (la tabla de precio del ítem en sí, no la del desglose de
    la receta más abajo)."""
    m = re.search(
        rf'<td[^>]*data-source="{re.escape(source)}"[^>]*>(.*?)</td>',
        html, re.DOTALL,
    )
    if not m:
        return ""
    return strip_tags(m.group(1)).strip()


def parse_recipe_items(html: str) -> list:
    """La receta es una tabla anidada de imágenes; se recuperan los
    nombres de los ítems componentes vía los title="..." de los links
    dentro del bloque data-source="recipe"."""
    m = re.search(
        r'data-source="recipe"[^>]*>(.*?)<section',
        html, re.DOTALL,
    )
    if not m:
        return []
    block = m.group(1)
    raw_names = re.findall(r'<a href="/wiki/[^"]+" title="([^"]+)"', block)
    names = [n.replace("&#39;", "'").replace("&amp;", "&").replace("&quot;", '"') for n in raw_names]
    return list(dict.fromkeys(names))


def parse_item_page(name: str) -> dict:
    html = fetch_page_html(name)
    recipe = parse_recipe_items(html)
    recipe = [n for n in recipe if n != name]
    return {
        "nombre": name,
        "tipo": infobox_field(html, "type"),
        "precio_total": infobox_price_field(html, "total_price"),
        "precio_venta": infobox_price_field(html, "sell"),
        "stats": infobox_field(html, "bonus"),
        "pasivo": infobox_field(html, "unique"),
        "receta": recipe,
    }


def parse_hero_page(name: str) -> dict:
    html = fetch_page_html(name)
    return {
        "nombre": name,
        "rol": infobox_field(html, "role"),
        "especialidad": infobox_field(html, "specialty"),
        "lane": infobox_field(html, "lane"),
        "tipo_dano": infobox_field(html, "dmg_type"),
        "tipo_ataque": infobox_field(html, "atk_type"),
        "durabilidad": infobox_field(html, "durability"),
        "ofensiva": infobox_field(html, "offense"),
        "dificultad": infobox_field(html, "difficulty"),
    }


def list_item_titles() -> list:
    titles = []
    cmcontinue = None
    while True:
        params = {
            "action": "query", "list": "categorymembers",
            "cmtitle": "Category:Equipment", "cmlimit": "500", "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_get(params)
        titles.extend(m["title"] for m in data["query"]["categorymembers"])
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    return sorted(titles)


def list_hero_titles() -> list:
    html = fetch_page_html("List_of_heroes")
    rows = re.findall(r"<tr\b.*?</tr>", html, re.DOTALL)
    names = []
    for row in rows:
        m = re.search(r'<a[^>]*title="([^"]+)"', row)
        icon = re.search(r'Hero\d+-icon\.png', row)
        if m and icon:
            names.append(m.group(1))
    return sorted(set(names))


def update_items() -> None:
    print("Descargando stats de ítems...")
    titles = list_item_titles()
    print(f"  {len(titles)} ítems en la categoría.")
    result = {}
    failed = []
    for i, name in enumerate(titles, 1):
        try:
            result[name] = parse_item_page(name)
        except Exception as e:
            failed.append((name, str(e)))
        if i % 20 == 0:
            print(f"  ...{i}/{len(titles)}")
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ITEMS_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  Guardados {len(result)} ítems en {ITEMS_JSON.relative_to(ROOT)}. Fallidos: {len(failed)}")
    for name, err in failed:
        print(f"    - {name}: {err}")


def update_heroes() -> None:
    print("Descargando datos de héroes...")
    titles = list_hero_titles()
    print(f"  {len(titles)} héroes encontrados.")
    result = {}
    failed = []
    for i, name in enumerate(titles, 1):
        try:
            result[name] = parse_hero_page(name)
        except Exception as e:
            failed.append((name, str(e)))
        if i % 20 == 0:
            print(f"  ...{i}/{len(titles)}")
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(HEROES_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  Guardados {len(result)} héroes en {HEROES_JSON.relative_to(ROOT)}. Fallidos: {len(failed)}")
    for name, err in failed:
        print(f"    - {name}: {err}")


if __name__ == "__main__":
    update_items()
    update_heroes()
    print("\nListo. Revisá data/knowledge/items.json y heroes.json.")
