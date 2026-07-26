"""
Fase 5: base de datos histórica (SQLite). Cada captura procesada agrega
1 fila en `matches` y 10 filas en `match_players`.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "db" / "mlbb.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mlbb_username TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    creado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER REFERENCES users(id),
    fecha TEXT NOT NULL,
    duracion TEXT,
    resultado TEXT,
    marcador_propio INTEGER,
    marcador_enemigo INTEGER,
    screenshot TEXT UNIQUE,
    content_hash TEXT,
    analisis TEXT
);

CREATE TABLE IF NOT EXISTS match_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    lado TEXT NOT NULL,
    jugador TEXT,
    heroe TEXT,
    item_1 TEXT,
    item_2 TEXT,
    item_3 TEXT,
    item_4 TEXT,
    item_5 TEXT,
    item_6 TEXT,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    oro INTEGER,
    rating REAL,
    mvp_flag INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Migración liviana: bases creadas antes de agregar content_hash no lo
    # tienen todavía (el nombre de archivo por sí solo no alcanza para
    # detectar duplicados: la app de capturas reutiliza nombres como
    # "Captura.PNG" para fotos distintas).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    if "content_hash" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN content_hash TEXT")
    if "analisis" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN analisis TEXT")
    if "usuario_id" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN usuario_id INTEGER REFERENCES users(id)")
        conn.commit()
        _backfill_default_user(conn)
    user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "password_hash" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    conn.commit()


def _backfill_default_user(conn: sqlite3.Connection) -> None:
    """Fase 9 (multi-usuario): las partidas cargadas antes de que existiera
    la tabla `users` no tienen usuario_id. Se les asigna la cuenta del
    `mlbb_username` configurado en config.json, que hasta ahora era el único
    usuario implícito del proyecto."""
    huerfanas = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE usuario_id IS NULL"
    ).fetchone()[0]
    if not huerfanas:
        return
    with open(ROOT / "config.json", encoding="utf-8") as f:
        username = json.load(f)["mlbb_username"]
    user_id = get_or_create_user(conn, username)
    conn.execute("UPDATE matches SET usuario_id = ? WHERE usuario_id IS NULL", (user_id,))
    conn.commit()


def get_or_create_user(conn: sqlite3.Connection, mlbb_username: str) -> int:
    """El nombre se normaliza a minúsculas para que da igual cómo venga
    tipeado (config.json vs. lo que lea el OCR): siempre es la misma cuenta."""
    normalized = mlbb_username.lower()
    row = conn.execute(
        "SELECT id FROM users WHERE mlbb_username = ?", (normalized,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO users (mlbb_username, creado) VALUES (?, ?)",
        (normalized, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_username(conn: sqlite3.Connection, mlbb_username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE mlbb_username = ?", (mlbb_username.lower(),)
    ).fetchone()


def set_password(conn: sqlite3.Connection, user_id: int, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    conn.commit()


def screenshot_hash_already_processed(conn: sqlite3.Connection, content_hash: str, usuario_id: int) -> bool:
    """Scopeado por usuario: si dos cuentas distintas suben la misma
    captura (ej. dos compañeros de la misma partida subiendo cada uno la
    suya), cada una tiene que quedar registrada, no solo la primera."""
    row = conn.execute(
        "SELECT 1 FROM matches WHERE content_hash = ? AND usuario_id = ?", (content_hash, usuario_id)
    ).fetchone()
    return row is not None


def save_analysis(conn: sqlite3.Connection, match_id: int, texto: str) -> None:
    conn.execute("UPDATE matches SET analisis = ? WHERE id = ?", (texto, match_id))
    conn.commit()


def insert_match(conn: sqlite3.Connection, match: dict) -> int:
    cur = conn.execute(
        """INSERT INTO matches (usuario_id, fecha, duracion, resultado, marcador_propio, marcador_enemigo, screenshot, content_hash)
           VALUES (:usuario_id, :fecha, :duracion, :resultado, :marcador_propio, :marcador_enemigo, :screenshot, :content_hash)""",
        match,
    )
    conn.commit()
    return cur.lastrowid


def insert_player(conn: sqlite3.Connection, match_id: int, player: dict) -> None:
    row = {"match_id": match_id, **player}
    conn.execute(
        """INSERT INTO match_players
           (match_id, lado, jugador, heroe, item_1, item_2, item_3, item_4, item_5, item_6,
            kills, deaths, assists, oro, rating, mvp_flag)
           VALUES
           (:match_id, :lado, :jugador, :heroe, :item_1, :item_2, :item_3, :item_4, :item_5, :item_6,
            :kills, :deaths, :assists, :oro, :rating, :mvp_flag)""",
        row,
    )
    conn.commit()
