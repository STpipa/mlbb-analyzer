"""
Fase 8: dashboard web. Sirve sobre la misma base SQLite que ya llenan
procesar.py / exportar_excel.py — no duplica nada de la lectura de
capturas, solo agrega una capa de visualización + el botón para pedirle
el análisis de coach a Claude (Fase 7) sin pasar por la consola.

Fase 9 (multi-usuario): login real con contraseña (hash en auth.py) +
sesión en cookie firmada (SessionMiddleware). Cada cuenta ve únicamente sus
propias partidas (ver stats.py). La cuenta que ya existía desde antes del
login (creada por procesar.py a partir de config.json) no tiene contraseña
todavía — /registro la "reclama" con la primera contraseña que se le ponga
en vez de rechazarla por nombre repetido.

Uso:
  uvicorn src.webapp:app --reload
"""
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import analizar_partida
import auth
import database as db
import icon_recognition as ic
import procesar
import stats

ROOT = Path(__file__).resolve().parent.parent
SECRET_FILE = ROOT / "data" / ".session_secret"
templates = Jinja2Templates(directory=str(ROOT / "templates"))

# Tope de análisis de coach (Fase 7) por cuenta: cada uno gasta la
# ANTHROPIC_API_KEY del host, así que sin límite un usuario curioso podría
# vaciar el crédito de quien hostea. Ajustable a mano según cuánto crédito
# quieras dejar disponible por persona.
MAX_ANALISIS_POR_USUARIO = 10

app = FastAPI(title="MLBB Analyzer")


def _load_or_create_secret() -> str:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


app.add_middleware(SessionMiddleware, secret_key=_load_or_create_secret())

# Arte de la wiki (Fase 1, update_reference.py) para mostrar íconos en el
# detalle de partida. A propósito NO se sirven heroes_learned/items_learned
# acá: son recortes reales de capturas de usuarios, no arte para mostrar
# públicamente, y su nombre de archivo puede traer la etiqueta de revisión.
_HEROES_ICONS_DIR = ROOT / "data" / "reference" / "heroes"
_ITEMS_ICONS_DIR = ROOT / "data" / "reference" / "items"
if _HEROES_ICONS_DIR.exists():
    app.mount("/iconos/heroes", StaticFiles(directory=str(_HEROES_ICONS_DIR)), name="iconos_heroes")
if _ITEMS_ICONS_DIR.exists():
    app.mount("/iconos/items", StaticFiles(directory=str(_ITEMS_ICONS_DIR)), name="iconos_items")


def get_conn():
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
    conn = get_conn()
    try:
        user = db.get_user_by_username(conn, username)
    finally:
        conn.close()
    if not user or not user["password_hash"] or not auth.verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Usuario o contraseña incorrectos."}, status_code=401
        )
    if db.ban_activo(user["banned_until"]):
        if user["banned_until"] == "permanente":
            error = "Esta cuenta fue bloqueada de forma permanente."
        else:
            hasta = datetime.fromisoformat(user["banned_until"]).strftime("%d/%m/%Y %H:%M")
            error = f"Esta cuenta está bloqueada hasta el {hasta}."
        return templates.TemplateResponse(request, "login.html", {"error": error}, status_code=403)
    request.session["user_id"] = user["id"]
    request.session["username"] = user["mlbb_username"]
    request.session["is_admin"] = bool(user["is_admin"])
    return RedirectResponse("/", status_code=303)


@app.get("/registro", response_class=HTMLResponse)
def registro_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "registro.html", {"error": None})


@app.post("/registro")
def registro_submit(request: Request, username: str = Form(""), password: str = Form("")):
    username = username.strip()
    if len(username) < 3 or len(password) < 4:
        error = "El usuario necesita al menos 3 caracteres y la contraseña al menos 4."
        return templates.TemplateResponse(request, "registro.html", {"error": error}, status_code=400)

    conn = get_conn()
    try:
        existing = db.get_user_by_username(conn, username)
        if existing and existing["password_hash"]:
            error = "Ese usuario ya existe. Si sos vos, iniciá sesión."
            return templates.TemplateResponse(request, "registro.html", {"error": error}, status_code=409)
        # existing sin password_hash = la cuenta que armó procesar.py antes de
        # que existiera el login; se "reclama" poniéndole la contraseña ahora.
        user_id = existing["id"] if existing else db.get_or_create_user(conn, username)
        db.set_password(conn, user_id, auth.hash_password(password))
        es_admin = bool(existing["is_admin"]) if existing else False
    finally:
        conn.close()

    request.session["user_id"] = user_id
    request.session["username"] = username.lower()
    request.session["is_admin"] = es_admin
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def require_login(request: Request) -> int | None:
    return request.session.get("user_id")


def es_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        resumen = stats.get_summary(conn, usuario_id)
        partidas = stats.get_matches(conn, usuario_id)
        heroes = stats.get_hero_stats(conn, usuario_id)
        tendencia = stats.get_rating_trend(conn, usuario_id)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "resumen": resumen,
            "partidas": partidas,
            "heroes": heroes,
            "tendencia": tendencia,
            "username": request.session.get("username"),
        },
    )


@app.get("/calidad", response_class=HTMLResponse)
def calidad_datos(request: Request):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        resumen = stats.get_calidad_datos(conn, usuario_id)
        tendencia = stats.get_calidad_tendencia(conn, usuario_id)
    finally:
        conn.close()
    cola_revision = len(list(ic.REVIEW_DIR.glob("*.png"))) if ic.REVIEW_DIR.exists() else 0
    return templates.TemplateResponse(
        request,
        "calidad.html",
        {
            "resumen": resumen,
            "tendencia": tendencia,
            "cola_revision": cola_revision,
            "username": request.session.get("username"),
        },
    )


@app.get("/partida/{match_id}", response_class=HTMLResponse)
def partida_detalle(request: Request, match_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        detalle = stats.get_match_detail(conn, match_id, usuario_id)
    finally:
        conn.close()
    if detalle is None:
        raise HTTPException(status_code=404, detail="Partida no encontrada")
    return templates.TemplateResponse(
        request,
        "partida.html",
        {"match_id": match_id, "username": request.session.get("username"), **detalle},
    )


@app.post("/partida/{match_id}/analizar")
def generar_analisis(request: Request, match_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        detalle = stats.get_match_detail(conn, match_id, usuario_id)
    finally:
        conn.close()
    if detalle is None:
        raise HTTPException(status_code=404, detail="Partida no encontrada")

    conn = get_conn()
    try:
        usados = stats.count_analisis(conn, usuario_id)
    finally:
        conn.close()
    if usados >= MAX_ANALISIS_POR_USUARIO:
        raise HTTPException(
            status_code=429,
            detail=f"Llegaste al límite de {MAX_ANALISIS_POR_USUARIO} análisis de coach para tu cuenta.",
        )

    try:
        analizar_partida.analizar(match_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return HTMLResponse(
        f'<meta http-equiv="refresh" content="0; url=/partida/{match_id}">'
    )


@app.get("/subir", response_class=HTMLResponse)
def subir_form(request: Request):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "subir.html", {"username": request.session.get("username"), "error": None}
    )


@app.post("/subir")
async def subir_submit(request: Request, captura: UploadFile = File(...)):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    username = request.session.get("username")

    procesar.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(captura.filename or "captura.png").suffix or ".png"
    dest_path = procesar.SCREENSHOTS_DIR / f"subida_{secrets.token_hex(6)}{suffix}"
    dest_path.write_bytes(await captura.read())

    conn = get_conn()
    try:
        try:
            match_id, motivo = procesar.process_screenshot(dest_path, username, usuario_id, conn)
        except Exception as e:
            dest_path.unlink(missing_ok=True)
            return templates.TemplateResponse(
                request,
                "subir.html",
                {"username": username, "error": f"No se pudo procesar la captura: {e}"},
                status_code=400,
            )
    finally:
        conn.close()

    if match_id is None:
        return templates.TemplateResponse(
            request,
            "subir.html",
            {"username": username, "error": motivo or "No se pudo procesar la captura."},
            status_code=409,
        )
    return RedirectResponse(f"/partida/{match_id}", status_code=303)


# ---------------------------------------------------------------------------
# Fase 10: administración (banear/bloquear cuentas). Sin flujo de "olvidé mi
# contraseña" (ver reset_password.py); esto sigue el mismo criterio, pero
# para moderación: quien ya es admin (otorgado por set_admin.py, a mano en el
# host) puede bloquear cuentas problemáticas desde la web sin tocar la base
# directamente.
# ---------------------------------------------------------------------------

_DURACIONES_BAN_DIAS = {"1": 1, "7": 7, "30": 30}


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    if not es_admin(request):
        raise HTTPException(status_code=403, detail="No tenés permisos de administrador.")
    conn = get_conn()
    try:
        usuarios = [dict(u) for u in db.list_users(conn)]
    finally:
        conn.close()
    for u in usuarios:
        u["bloqueado"] = db.ban_activo(u["banned_until"])
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"usuarios": usuarios, "usuario_actual_id": usuario_id, "username": request.session.get("username")},
    )


@app.post("/admin/usuarios/{user_id}/ban")
def admin_ban(request: Request, user_id: int, duracion: str = Form(...)):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    if not es_admin(request):
        raise HTTPException(status_code=403, detail="No tenés permisos de administrador.")
    if user_id == usuario_id:
        raise HTTPException(status_code=400, detail="No podés bloquearte a vos mismo.")
    conn = get_conn()
    try:
        objetivo = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if objetivo is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        if objetivo["is_admin"]:
            raise HTTPException(status_code=400, detail="No se puede bloquear a otro administrador.")
        if duracion == "permanente":
            banned_until = "permanente"
        else:
            dias = _DURACIONES_BAN_DIAS.get(duracion)
            if dias is None:
                raise HTTPException(status_code=400, detail="Duración inválida.")
            banned_until = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat(timespec="seconds")
        db.set_ban(conn, user_id, banned_until)
    finally:
        conn.close()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/usuarios/{user_id}/desbloquear")
def admin_unban(request: Request, user_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    if not es_admin(request):
        raise HTTPException(status_code=403, detail="No tenés permisos de administrador.")
    conn = get_conn()
    try:
        db.set_ban(conn, user_id, None)
    finally:
        conn.close()
    return RedirectResponse("/admin", status_code=303)


# ---------------------------------------------------------------------------
# Fase 10: amigos. Cada cuenta sigue siendo dueña de sus propias partidas y
# genera su propio análisis de coach (gasta su propio cupo de
# MAX_ANALISIS_POR_USUARIO) — lo que agrega esta sección es la posibilidad de
# mirar en modo solo-lectura las partidas y análisis ya generados de un
# amigo, para comparar entre compañeros de equipo. No hay forma de enlazar
# automáticamente "esta es la misma partida que subió mi amigo": cada
# captura no trae ningún ID de partida real, así que juntar las dos
# perspectivas de una misma partida jugada en equipo queda, por ahora, en
# manos de mirar fecha/hora de cada una a simple vista.
# ---------------------------------------------------------------------------


@app.get("/amigos", response_class=HTMLResponse)
def amigos_panel(request: Request, q: str = ""):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        amigos = db.get_amigos(conn, usuario_id)
        recibidas = db.get_solicitudes_recibidas(conn, usuario_id)
        enviadas = db.get_solicitudes_enviadas(conn, usuario_id)
        resultados = db.buscar_usuarios(conn, q, usuario_id) if q.strip() else []
    finally:
        conn.close()
    nombres_relacionados = (
        {a["mlbb_username"] for a in amigos}
        | {r["mlbb_username"] for r in recibidas}
        | {e["mlbb_username"] for e in enviadas}
    )
    resultados = [r for r in resultados if r["mlbb_username"] not in nombres_relacionados]
    return templates.TemplateResponse(
        request,
        "amigos.html",
        {
            "amigos": amigos,
            "recibidas": recibidas,
            "enviadas": enviadas,
            "resultados": resultados,
            "q": q,
            "error": request.session.pop("flash_error", None),
            "username": request.session.get("username"),
        },
    )


@app.post("/amigos/solicitar")
def amigos_solicitar(request: Request, destinatario_username: str = Form(...)):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        destinatario = db.get_user_by_username(conn, destinatario_username)
        if destinatario is None or not destinatario["password_hash"]:
            request.session["flash_error"] = "No existe ese usuario."
        else:
            error = db.enviar_solicitud_amistad(conn, usuario_id, destinatario["id"])
            if error:
                request.session["flash_error"] = error
    finally:
        conn.close()
    return RedirectResponse("/amigos", status_code=303)


@app.post("/amigos/{friendship_id}/aceptar")
def amigos_aceptar(request: Request, friendship_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        db.responder_solicitud_amistad(conn, friendship_id, usuario_id, aceptar=True)
    finally:
        conn.close()
    return RedirectResponse("/amigos", status_code=303)


@app.post("/amigos/{friendship_id}/rechazar")
def amigos_rechazar(request: Request, friendship_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        db.responder_solicitud_amistad(conn, friendship_id, usuario_id, aceptar=False)
    finally:
        conn.close()
    return RedirectResponse("/amigos", status_code=303)


@app.get("/amigos/{friend_id}/partidas", response_class=HTMLResponse)
def amigo_partidas(request: Request, friend_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        if not db.son_amigos(conn, usuario_id, friend_id):
            raise HTTPException(status_code=403, detail="Esa cuenta no es tu amiga.")
        amigo = conn.execute("SELECT mlbb_username FROM users WHERE id = ?", (friend_id,)).fetchone()
        partidas = stats.get_matches(conn, friend_id)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "amigo_partidas.html",
        {
            "partidas": partidas,
            "amigo_id": friend_id,
            "amigo_nombre": amigo["mlbb_username"],
            "username": request.session.get("username"),
        },
    )


@app.get("/amigos/{friend_id}/partida/{match_id}", response_class=HTMLResponse)
def amigo_partida_detalle(request: Request, friend_id: int, match_id: int):
    usuario_id = require_login(request)
    if not usuario_id:
        return RedirectResponse("/login", status_code=303)
    conn = get_conn()
    try:
        if not db.son_amigos(conn, usuario_id, friend_id):
            raise HTTPException(status_code=403, detail="Esa cuenta no es tu amiga.")
        amigo = conn.execute("SELECT mlbb_username FROM users WHERE id = ?", (friend_id,)).fetchone()
        detalle = stats.get_match_detail(conn, match_id, friend_id)
    finally:
        conn.close()
    if detalle is None:
        raise HTTPException(status_code=404, detail="Partida no encontrada")
    return templates.TemplateResponse(
        request,
        "partida.html",
        {
            "match_id": match_id,
            "username": request.session.get("username"),
            "solo_lectura": True,
            "amigo_nombre": amigo["mlbb_username"],
            "volver_url": f"/amigos/{friend_id}/partidas",
            **detalle,
        },
    )
