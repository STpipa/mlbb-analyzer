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
    creado TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    banned_until TEXT
);

CREATE TABLE IF NOT EXISTS friendships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitante_id INTEGER NOT NULL REFERENCES users(id),
    destinatario_id INTEGER NOT NULL REFERENCES users(id),
    estado TEXT NOT NULL DEFAULT 'pendiente',
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
    if "is_admin" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if "banned_until" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN banned_until TEXT")
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


def set_admin(conn: sqlite3.Connection, user_id: int, es_admin: bool) -> None:
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if es_admin else 0, user_id))
    conn.commit()


def set_ban(conn: sqlite3.Connection, user_id: int, banned_until: str | None) -> None:
    """`banned_until` es None (sin bloqueo), la cadena literal "permanente",
    o un ISO datetime hasta el cual dura el bloqueo temporal."""
    conn.execute("UPDATE users SET banned_until = ? WHERE id = ?", (banned_until, user_id))
    conn.commit()


def ban_activo(banned_until: str | None) -> bool:
    if not banned_until:
        return False
    if banned_until == "permanente":
        return True
    try:
        return datetime.fromisoformat(banned_until) > datetime.now(timezone.utc)
    except ValueError:
        return False


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users ORDER BY mlbb_username").fetchall()


def enviar_solicitud_amistad(conn: sqlite3.Connection, solicitante_id: int, destinatario_id: int) -> str | None:
    """Devuelve None si se creó bien, o un mensaje de error si no corresponde
    (a uno mismo, ya son amigos, ya hay una solicitud pendiente en cualquier
    dirección)."""
    if solicitante_id == destinatario_id:
        return "No podés agregarte a vos mismo."
    existente = conn.execute(
        """SELECT estado FROM friendships
           WHERE (solicitante_id = ? AND destinatario_id = ?)
              OR (solicitante_id = ? AND destinatario_id = ?)""",
        (solicitante_id, destinatario_id, destinatario_id, solicitante_id),
    ).fetchone()
    if existente:
        return "Ya son amigos." if existente[0] == "aceptado" else "Ya hay una solicitud pendiente."
    conn.execute(
        "INSERT INTO friendships (solicitante_id, destinatario_id, estado, creado) VALUES (?, ?, 'pendiente', ?)",
        (solicitante_id, destinatario_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()
    return None


def responder_solicitud_amistad(conn: sqlite3.Connection, friendship_id: int, user_id: int, aceptar: bool) -> bool:
    """Solo el destinatario puede aceptar; destinatario o solicitante pueden
    cancelar/rechazar (elimina la fila, no queda historial de rechazos).
    Devuelve False si la solicitud no existe o no le corresponde a este
    usuario tocarla."""
    row = conn.execute("SELECT * FROM friendships WHERE id = ?", (friendship_id,)).fetchone()
    if row is None:
        return False
    if aceptar:
        if row["destinatario_id"] != user_id or row["estado"] != "pendiente":
            return False
        conn.execute("UPDATE friendships SET estado = 'aceptado' WHERE id = ?", (friendship_id,))
    else:
        if user_id not in (row["destinatario_id"], row["solicitante_id"]):
            return False
        conn.execute("DELETE FROM friendships WHERE id = ?", (friendship_id,))
    conn.commit()
    return True


def get_solicitudes_recibidas(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT f.id, f.creado, u.mlbb_username
           FROM friendships f JOIN users u ON u.id = f.solicitante_id
           WHERE f.destinatario_id = ? AND f.estado = 'pendiente'
           ORDER BY f.creado""",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_solicitudes_enviadas(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT f.id, f.creado, u.mlbb_username
           FROM friendships f JOIN users u ON u.id = f.destinatario_id
           WHERE f.solicitante_id = ? AND f.estado = 'pendiente'
           ORDER BY f.creado""",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_amigos(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT u.id, u.mlbb_username
           FROM friendships f
           JOIN users u ON u.id = (CASE WHEN f.solicitante_id = ? THEN f.destinatario_id ELSE f.solicitante_id END)
           WHERE (f.solicitante_id = ? OR f.destinatario_id = ?) AND f.estado = 'aceptado'
           ORDER BY u.mlbb_username""",
        (user_id, user_id, user_id),
    ).fetchall()
    return [dict(r) for r in rows]


def son_amigos(conn: sqlite3.Connection, user_id_a: int, user_id_b: int) -> bool:
    row = conn.execute(
        """SELECT 1 FROM friendships
           WHERE estado = 'aceptado'
             AND ((solicitante_id = ? AND destinatario_id = ?)
               OR (solicitante_id = ? AND destinatario_id = ?))""",
        (user_id_a, user_id_b, user_id_b, user_id_a),
    ).fetchone()
    return row is not None


def buscar_usuarios(conn: sqlite3.Connection, query: str, excluir_id: int, limite: int = 10) -> list[dict]:
    rows = conn.execute(
        """SELECT id, mlbb_username FROM users
           WHERE mlbb_username LIKE ? AND id != ? AND password_hash IS NOT NULL
           ORDER BY mlbb_username LIMIT ?""",
        (f"%{query.lower()}%", excluir_id, limite),
    ).fetchall()
    return [dict(r) for r in rows]


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


def set_screenshot_name(conn: sqlite3.Connection, match_id: int, screenshot: str) -> None:
    conn.execute("UPDATE matches SET screenshot = ? WHERE id = ?", (screenshot, match_id))
    conn.commit()


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
