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
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import analizar_partida
import auth
import database as db
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
    request.session["user_id"] = user["id"]
    request.session["username"] = user["mlbb_username"]
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
    finally:
        conn.close()

    request.session["user_id"] = user_id
    request.session["username"] = username.lower()
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def require_login(request: Request) -> int | None:
    return request.session.get("user_id")


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
            match_id = procesar.process_screenshot(dest_path, username, usuario_id, conn)
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
            {"username": username, "error": "Esa captura ya la habías subido antes."},
            status_code=409,
        )
    return RedirectResponse(f"/partida/{match_id}", status_code=303)
