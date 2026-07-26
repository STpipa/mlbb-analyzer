"""
Fase 7: motor de análisis/coaching. Toma una partida ya cargada en la base
(database.py) + la base de conocimiento de ítems y héroes (update_knowledge.py)
y le pide a la API de Claude un análisis de qué estuvo bien y mal, con la
misma info que tendría un jugador mirando la pantalla de resultados.

No inventa reglas de counters a mano: le pasa los datos concretos de la
partida (tu build, tus stats, héroes e ítems rivales) más los stats reales
de esos ítems/héroes, y deja que el modelo razone. Si algo no se pudo
reconocer (héroe/ítem "None" porque quedó en revisión pendiente), se lo
avisa al modelo explícitamente para que no invente ni lo ignore en silencio.

Uso:
  python src/analizar_partida.py            -> analiza la última partida cargada
  python src/analizar_partida.py <match_id> -> analiza esa partida puntual

Requiere la variable de entorno ANTHROPIC_API_KEY.
"""
import json
import os
import sys
from pathlib import Path

import anthropic

import database as db

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
ANALISIS_DIR = ROOT / "data" / "analisis"
MODEL = "claude-sonnet-5"


def load_knowledge() -> tuple[dict, dict]:
    items_path = KNOWLEDGE_DIR / "items.json"
    heroes_path = KNOWLEDGE_DIR / "heroes.json"
    if not items_path.exists() or not heroes_path.exists():
        raise FileNotFoundError(
            "Falta data/knowledge/items.json o heroes.json. Corré primero: python src/update_knowledge.py"
        )
    with open(items_path, encoding="utf-8") as f:
        items = json.load(f)
    with open(heroes_path, encoding="utf-8") as f:
        heroes = json.load(f)
    return items, heroes


def get_match_id(conn, requested: str | None) -> int:
    if requested:
        return int(requested)
    row = conn.execute("SELECT id FROM matches ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError("No hay partidas cargadas en la base todavía.")
    return row[0]


def get_match(conn, match_id: int) -> dict:
    match = conn.execute(
        "SELECT id, fecha, duracion, resultado, marcador_propio, marcador_enemigo, screenshot "
        "FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if not match:
        raise ValueError(f"No existe la partida match_id={match_id}")
    cols = ["id", "fecha", "duracion", "resultado", "marcador_propio", "marcador_enemigo", "screenshot"]
    match = dict(zip(cols, match))

    player_cols = [
        "lado", "jugador", "heroe", "item_1", "item_2", "item_3", "item_4", "item_5", "item_6",
        "kills", "deaths", "assists", "oro", "rating", "mvp_flag",
    ]
    rows = conn.execute(
        f"SELECT {', '.join(player_cols)} FROM match_players WHERE match_id = ? ORDER BY lado",
        (match_id,),
    ).fetchall()
    players = [dict(zip(player_cols, r)) for r in rows]
    match["jugadores"] = players
    return match


def _hero_summary(heroes: dict, name: str | None) -> str:
    if not name or name not in heroes:
        return "(sin datos)"
    h = heroes[name]
    return (
        f"rol={h['rol']}, especialidad={h['especialidad']}, lane={h['lane']}, "
        f"tipo_dano={h['tipo_dano']}, tipo_ataque={h['tipo_ataque']}, "
        f"durabilidad={h['durabilidad']}/10, ofensiva={h['ofensiva']}/10, dificultad={h['dificultad']}/10"
    )


def _item_summary(items: dict, name: str | None) -> str:
    if not name:
        return None
    if name not in items:
        return f"{name} (sin datos en la base de conocimiento)"
    it = items[name]
    stats = it["stats"].replace("\n", " ") if it["stats"] else "(sin stats registrados)"
    pasivo = f" | Pasivo: {it['pasivo']}" if it["pasivo"] else ""
    return f"{name} [{it['tipo']}, {it['precio_total']} oro]: {stats}{pasivo}"


def build_prompt(match: dict, items: dict, heroes: dict, username: str) -> str:
    lineas = []
    lineas.append(
        f"Partida del {match['fecha']}, resultado {match['resultado']}, "
        f"marcador {match['marcador_propio']}-{match['marcador_enemigo']}, duración: {match['duracion']}."
    )
    lineas.append("")

    for lado, titulo in (("yo", f"JUGADOR ANALIZADO ({username})"), ("aliado", "ALIADOS"), ("rival", "RIVALES")):
        jugadores = [p for p in match["jugadores"] if p["lado"] == lado]
        if not jugadores:
            continue
        lineas.append(f"== {titulo} ==")
        for p in jugadores:
            heroe = p["heroe"] or "(no reconocido)"
            mvp = " [MVP]" if p["mvp_flag"] else ""
            lineas.append(
                f"- {p['jugador'] or '(nombre no legible)'} | Héroe: {heroe} ({_hero_summary(heroes, p['heroe'])}) "
                f"| Kills: {p['kills']} | Deaths (veces que murió): {p['deaths']} | Assists: {p['assists']} "
                f"| Oro: {p['oro']} | Rating: {p['rating']}{mvp}"
            )
            item_names = [p[f"item_{i}"] for i in range(1, 7)]
            resumido = [_item_summary(items, n) for n in item_names]
            for texto in resumido:
                if texto:
                    lineas.append(f"    · {texto}")
            faltantes = sum(1 for n in item_names if not n)
            if faltantes:
                lineas.append(f"    (quedaron {faltantes} slot(s) de ítem sin reconocer, no asumas qué eran)")
        lineas.append("")

    return "\n".join(lineas)


SYSTEM_PROMPT = """Sos un coach de Mobile Legends: Bang Bang analizando la partida de un jugador
a partir de los datos reales extraídos de su pantalla de post-partida (OCR + reconocimiento de
íconos), más datos reales de stats/pasivos de ítems y de héroes sacados del wiki oficial.

Reglas importantes:
- Basate únicamente en los datos concretos que te paso. Si algo dice "no reconocido" o "sin datos",
  no inventes qué era ni lo completes con una suposición.
- Citá los números (kills, deaths, assists, oro, rating) exactamente como te los paso, sin
  redondear ni confundirlos entre sí. Antes de escribir una cifra en la respuesta, releé el dato
  correspondiente del jugador analizado para confirmar que la copiaste bien.
- Enfocate en el jugador analizado: su elección de build contra la composición rival (tipos de daño,
  roles), el timing/orden de compra si se puede inferir, y su desempeño (KDA, oro, rating) comparado
  con el resto de la partida.
- Sé específico y accionable: no digas "mejorá tu farmeo" en general, decí qué ítem le faltaba dado
  lo que enfrentaba, o qué debería haber priorizado.
- Respondé en español rioplatense, tono directo de coach, sin rodeos ni relleno. Extensión: un párrafo
  de resumen general + una lista corta de puntos concretos (qué estuvo bien, qué faltó)."""


def analizar(match_id: int | None = None) -> tuple[int, str, Path]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta la variable de entorno ANTHROPIC_API_KEY. "
            "Configurala antes de correr este script (ver instrucciones)."
        )

    conn = db.get_connection()
    db.init_db(conn)
    resolved_id = get_match_id(conn, str(match_id) if match_id else None)
    match = get_match(conn, resolved_id)

    items, heroes = load_knowledge()
    with open(ROOT / "config.json", encoding="utf-8") as f:
        username = json.load(f)["mlbb_username"]

    prompt = build_prompt(match, items, heroes, username)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        thinking={"type": "disabled"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = "\n".join(block.text for block in response.content if block.type == "text")

    db.save_analysis(conn, resolved_id, texto)
    conn.close()

    ANALISIS_DIR.mkdir(parents=True, exist_ok=True)
    dest = ANALISIS_DIR / f"partida_{resolved_id}.txt"
    encabezado = (
        f"Partida {resolved_id} | {match['fecha']} | {match['resultado']} "
        f"{match['marcador_propio']}-{match['marcador_enemigo']}\n{'=' * 60}\n\n"
    )
    dest.write_text(encabezado + texto, encoding="utf-8")

    return resolved_id, texto, dest


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        match_id, texto, dest = analizar(int(arg) if arg else None)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(texto)
    print(f"\n{'-' * 60}")
    print(f"Guardado en: {dest}")
