"""
Descarga/actualiza los íconos de referencia (héroes e ítems) de MLBB
desde el wiki de Fandom (mobile-legends.fandom.com), vía su API pública
de MediaWiki. Se puede volver a correr cuando salga un héroe/ítem nuevo
o cambien los íconos en un parche.

Uso: python src/update_reference.py
"""
import io
import re
import json
import urllib.request
import urllib.parse
from pathlib import Path

from PIL import Image

WIKI_API = "https://mobile-legends.fandom.com/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (mlbb-analyzer reference updater)"}

ROOT = Path(__file__).resolve().parent.parent
HEROES_DIR = ROOT / "data" / "reference" / "heroes"
ITEMS_DIR = ROOT / "data" / "reference" / "items"
ICON_SIZE = 128

FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    return FORBIDDEN_CHARS.sub("", name).strip()


def api_get(params: dict) -> dict:
    url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_rendered_html(page_title: str) -> str:
    data = api_get({
        "action": "parse",
        "page": page_title,
        "prop": "text",
        "format": "json",
    })
    return data["parse"]["text"]["*"]


def get_file_url(file_title: str) -> str | None:
    data = api_get({
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    })
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        if "imageinfo" in page:
            return page["imageinfo"][0]["url"]
    return None


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def save_icon(raw: bytes, dest: Path) -> None:
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    offset = ((ICON_SIZE - img.width) // 2, (ICON_SIZE - img.height) // 2)
    canvas.paste(img, offset, img)
    canvas.save(dest, "PNG")


def parse_hero_icon_urls(html: str) -> dict:
    """Empareja cada héroe con su ícono cuadrado buscando fila por fila
    en la tabla de List_of_heroes (nombre = primer link con título,
    ícono = imagen Hero###-icon.png de esa misma fila)."""
    rows = re.findall(r"<tr\b.*?</tr>", html, re.DOTALL)
    result = {}
    for row in rows:
        name_match = re.search(r'<a[^>]*title="([^"]+)"', row)
        icon_match = re.search(
            r'(?:data-src|src)="([^"]*Hero\d+-icon\.png[^"]*)"', row
        )
        if name_match and icon_match:
            name = name_match.group(1)
            url = icon_match.group(1)
            url = re.sub(r"/scale-to-width-down/\d+", "", url)
            result[name] = url
    return result


def update_heroes() -> None:
    print("Descargando lista de héroes...")
    html = fetch_rendered_html("List_of_heroes")
    hero_urls = parse_hero_icon_urls(html)
    print(f"  {len(hero_urls)} héroes encontrados.")

    HEROES_DIR.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, []
    for name, url in sorted(hero_urls.items()):
        dest = HEROES_DIR / f"{sanitize_filename(name)}.png"
        try:
            raw = download_bytes(url)
            save_icon(raw, dest)
            ok += 1
        except Exception as e:
            failed.append((name, str(e)))
    print(f"  Héroes guardados: {ok}. Fallidos: {len(failed)}")
    for name, err in failed:
        print(f"    - {name}: {err}")


def update_items() -> None:
    print("Descargando lista de ítems (Category:Equipment)...")
    titles = []
    cmcontinue = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "Category:Equipment",
            "cmlimit": "500",
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_get(params)
        titles.extend(m["title"] for m in data["query"]["categorymembers"])
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    print(f"  {len(titles)} ítems listados en la categoría.")

    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    ok, skipped, failed = 0, [], []
    for name in sorted(titles):
        try:
            file_url = get_file_url(f"File:{name}.png")
            if not file_url:
                skipped.append(name)
                continue
            raw = download_bytes(file_url)
            dest = ITEMS_DIR / f"{sanitize_filename(name)}.png"
            save_icon(raw, dest)
            ok += 1
        except Exception as e:
            failed.append((name, str(e)))
    print(f"  Ítems guardados: {ok}. Sin ícono encontrado: {len(skipped)}. Fallidos: {len(failed)}")
    if skipped:
        print("  Sin ícono (revisar manualmente si hace falta):")
        for name in skipped:
            print(f"    - {name}")
    for name, err in failed:
        print(f"    - {name}: {err}")


if __name__ == "__main__":
    update_heroes()
    update_items()
    print("\nListo. Revisá data/reference/heroes y data/reference/items.")
