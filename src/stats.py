"""
Fase 8: consultas agregadas sobre la base para alimentar el dashboard web.
Todo gira en torno a la fila `lado='yo'` de cada partida (el jugador dueño
de esa partida). Fase 9 le suma `usuario_id` a todas las consultas para que
cada cuenta vea únicamente sus propias partidas.
"""
import sqlite3


def get_matches(conn: sqlite3.Connection, usuario_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT m.id, m.fecha, m.duracion, m.resultado, m.marcador_propio,
                  m.marcador_enemigo, m.analisis IS NOT NULL AS tiene_analisis,
                  p.heroe, p.kills, p.deaths, p.assists, p.oro, p.rating, p.mvp_flag
           FROM matches m
           LEFT JOIN match_players p ON p.match_id = m.id AND p.lado = 'yo'
           WHERE m.usuario_id = ?
           ORDER BY m.fecha DESC""",
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_match_detail(conn: sqlite3.Connection, match_id: int, usuario_id: int) -> dict | None:
    m = conn.execute(
        "SELECT * FROM matches WHERE id = ? AND usuario_id = ?", (match_id, usuario_id)
    ).fetchone()
    if m is None:
        return None
    players = conn.execute(
        "SELECT * FROM match_players WHERE match_id = ? ORDER BY lado, id", (match_id,)
    ).fetchall()
    return {
        "match": dict(m),
        "aliados": [dict(p) for p in players if p["lado"] in ("yo", "aliado")],
        "rivales": [dict(p) for p in players if p["lado"] == "rival"],
    }


def get_summary(conn: sqlite3.Connection, usuario_id: int) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN m.resultado = 'VICTORY' THEN 1 ELSE 0 END) AS victorias,
                  AVG(p.rating) AS rating_prom,
                  AVG(p.kills) AS kills_prom,
                  AVG(p.deaths) AS deaths_prom,
                  AVG(p.assists) AS assists_prom
           FROM matches m
           LEFT JOIN match_players p ON p.match_id = m.id AND p.lado = 'yo'
           WHERE m.usuario_id = ?""",
        (usuario_id,),
    ).fetchone()
    d = dict(row)
    d["winrate"] = round(100 * d["victorias"] / d["total"], 1) if d["total"] else 0.0
    return d


def get_hero_stats(conn: sqlite3.Connection, usuario_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT p.heroe,
                  COUNT(*) AS partidas,
                  SUM(CASE WHEN m.resultado = 'VICTORY' THEN 1 ELSE 0 END) AS victorias,
                  AVG(p.rating) AS rating_prom
           FROM match_players p
           JOIN matches m ON m.id = p.match_id
           WHERE p.lado = 'yo' AND p.heroe IS NOT NULL AND m.usuario_id = ?
           GROUP BY p.heroe
           ORDER BY partidas DESC""",
        (usuario_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["winrate"] = round(100 * d["victorias"] / d["partidas"], 1)
        result.append(d)
    return result


def get_rating_trend(conn: sqlite3.Connection, usuario_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT m.fecha, p.rating, p.heroe, m.resultado
           FROM match_players p
           JOIN matches m ON m.id = p.match_id
           WHERE p.lado = 'yo' AND p.rating IS NOT NULL AND m.usuario_id = ?
           ORDER BY m.fecha ASC""",
        (usuario_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_calidad_datos(conn: sqlite3.Connection, usuario_id: int) -> dict:
    """Resumen de cuánto reconoce bien el pipeline (héroes/ítems/nombres)
    para las partidas de esta cuenta. Antes la única forma de notar si esto
    empeoraba o mejoraba con un cambio era revisar la base a mano por
    casualidad (así se encontró el bug del corpus de ítems del
    2026-07-26) — con esto queda a la vista de un vistazo."""
    fila = conn.execute(
        """SELECT
             COUNT(*) AS filas,
             SUM(CASE WHEN p.heroe IS NULL THEN 1 ELSE 0 END) AS heroes_sin_reconocer,
             SUM(CASE WHEN p.jugador IS NULL OR p.jugador = '' THEN 1 ELSE 0 END) AS nombres_sin_reconocer,
             SUM(
               (p.item_1 IS NULL) + (p.item_2 IS NULL) + (p.item_3 IS NULL) +
               (p.item_4 IS NULL) + (p.item_5 IS NULL) + (p.item_6 IS NULL)
             ) AS items_sin_reconocer
           FROM match_players p
           JOIN matches m ON m.id = p.match_id
           WHERE m.usuario_id = ?""",
        (usuario_id,),
    ).fetchone()
    d = dict(fila)
    d["items_total"] = d["filas"] * 6

    def pct_ok(sin_reconocer, total):
        return round(100 * (1 - sin_reconocer / total), 1) if total else None

    d["pct_heroe_ok"] = pct_ok(d["heroes_sin_reconocer"], d["filas"])
    d["pct_item_ok"] = pct_ok(d["items_sin_reconocer"], d["items_total"])
    d["pct_nombre_ok"] = pct_ok(d["nombres_sin_reconocer"], d["filas"])
    return d


def get_calidad_tendencia(conn: sqlite3.Connection, usuario_id: int) -> list[dict]:
    """% de filas con héroe reconocido, una por partida y ordenado por
    fecha, para graficar si la calidad de reconocimiento mejora o empeora
    con el tiempo en vez de mirar un único número acumulado."""
    rows = conn.execute(
        """SELECT m.id, m.fecha,
                  COUNT(*) AS filas,
                  SUM(CASE WHEN p.heroe IS NULL THEN 1 ELSE 0 END) AS heroes_sin_reconocer
           FROM match_players p
           JOIN matches m ON m.id = p.match_id
           WHERE m.usuario_id = ?
           GROUP BY m.id
           ORDER BY m.fecha ASC""",
        (usuario_id,),
    ).fetchall()
    resultado = []
    for r in rows:
        d = dict(r)
        d["pct_heroe_ok"] = round(100 * (1 - d["heroes_sin_reconocer"] / d["filas"]), 1) if d["filas"] else 0.0
        resultado.append(d)
    return resultado


def count_analisis(conn: sqlite3.Connection, usuario_id: int) -> int:
    """Cuántas veces ya se generó un análisis de coach (Fase 7, consume la
    ANTHROPIC_API_KEY del host) para partidas de este usuario — para poner
    un tope y que un usuario curioso no vacíe el crédito de la cuenta."""
    return conn.execute(
        "SELECT COUNT(*) FROM matches WHERE usuario_id = ? AND analisis IS NOT NULL",
        (usuario_id,),
    ).fetchone()[0]
