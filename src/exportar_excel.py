"""
Fase 6: exporta toda la base histórica a un .xlsx con dos hojas:
  - "Datos crudos": una fila por jugador por partida.
  - "Resumen": winrate, KDA promedio y oro promedio por héroe jugado (vos).

Uso: python src/exportar_excel.py
"""
from pathlib import Path

import pandas as pd

import database as db

ROOT = Path(__file__).resolve().parent.parent
EXPORT_PATH = ROOT / "data" / "exports" / "mlbb_analysis.xlsx"

RAW_QUERY = """
SELECT
    m.id AS match_id,
    m.fecha,
    m.duracion,
    m.resultado,
    m.marcador_propio,
    m.marcador_enemigo,
    m.screenshot,
    p.lado,
    p.jugador,
    p.heroe,
    p.item_1, p.item_2, p.item_3, p.item_4, p.item_5, p.item_6,
    p.kills, p.deaths, p.assists, p.oro, p.rating, p.mvp_flag
FROM matches m
JOIN match_players p ON p.match_id = m.id
ORDER BY m.fecha, m.id, p.lado DESC
"""


def build_resumen(df_crudo: pd.DataFrame) -> pd.DataFrame:
    mias = df_crudo[(df_crudo["lado"] == "yo") & df_crudo["heroe"].notna()].copy()
    if mias.empty:
        return pd.DataFrame(
            columns=["heroe", "partidas", "winrate_%", "kda_promedio", "kills_prom",
                     "deaths_prom", "assists_prom", "oro_promedio", "rating_promedio"]
        )

    mias["gano"] = (mias["resultado"] == "VICTORY").astype(int)

    resumen = mias.groupby("heroe").agg(
        partidas=("match_id", "count"),
        winrate_pct=("gano", lambda s: round(100 * s.mean(), 1)),
        kills_prom=("kills", "mean"),
        deaths_prom=("deaths", "mean"),
        assists_prom=("assists", "mean"),
        oro_promedio=("oro", "mean"),
        rating_promedio=("rating", "mean"),
    ).reset_index()

    resumen["kda_promedio"] = (
        (resumen["kills_prom"] + resumen["assists_prom"]) / resumen["deaths_prom"].replace(0, pd.NA)
    ).round(2)

    for col in ("kills_prom", "deaths_prom", "assists_prom", "oro_promedio", "rating_promedio"):
        resumen[col] = resumen[col].round(2)

    resumen = resumen.sort_values("partidas", ascending=False)
    return resumen[[
        "heroe", "partidas", "winrate_pct", "kda_promedio",
        "kills_prom", "deaths_prom", "assists_prom", "oro_promedio", "rating_promedio",
    ]]


if __name__ == "__main__":
    conn = db.get_connection()
    db.init_db(conn)
    df_crudo = pd.read_sql_query(RAW_QUERY, conn)
    conn.close()

    if df_crudo.empty:
        print("La base todavía no tiene partidas cargadas (corré primero src/procesar.py).")
        raise SystemExit

    resumen = build_resumen(df_crudo)

    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(EXPORT_PATH, engine="openpyxl") as writer:
        df_crudo.to_excel(writer, sheet_name="Datos crudos", index=False)
        resumen.to_excel(writer, sheet_name="Resumen", index=False)

    print(f"Exportado: {EXPORT_PATH}")
    print(f"  {len(df_crudo)} filas de jugador en {df_crudo['match_id'].nunique()} partidas.")
    print(f"  {len(resumen)} héroes distintos en el resumen.")
