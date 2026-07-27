"""
Fase 4: extracción de texto (OCR) de una captura de post-partida ya
normalizada por layout.py — nombre de jugador, K/D/A, oro, rating, MVP,
marcador final y timer.

Este módulo nació durante la Fase 2 (para poder verificar que las
coordenadas del layout estaban bien puestas hacía falta leer el texto real),
así que ya viene validado contra las 5 capturas de muestra. Fase 5 importa
`extraer_partida()` para volcar los datos a la base SQLite.
"""
import difflib
import json
from pathlib import Path

import cv2
import pytesseract

import digit_recognition as digitrec
import layout
import name_recognition as namerec

ROOT = Path(__file__).resolve().parent.parent


def load_username() -> str:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)["mlbb_username"].lower()


def binarize(crop_bgr, scale=6):
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(resized, (3, 3), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


def pad(img, size=20):
    return cv2.copyMakeBorder(img, size, size, size, size, cv2.BORDER_CONSTANT, value=0)


def ocr_isolated_number(img, whitelist="0123456789"):
    """OCR de un recorte que contiene UN solo número aislado (ya con padding).
    Prueba varios --psm porque psm7 y psm8 se equivocan en casos distintos
    (uno falla con dígitos sueltos, el otro con números de 2+ dígitos)."""
    for psm in (8, 7, 10):
        txt = pytesseract.image_to_string(
            img, config=f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
        ).strip()
        if txt and all(c in whitelist for c in txt):
            return txt
    return ""


def ocr_text(img, psm=7):
    if img is None or img.size == 0:
        return ""
    return pytesseract.image_to_string(img, config=f"--psm {psm}").strip()


def split_stats_block(th, gap_threshold=45, inner_pad=15, expect=4):
    """K/D/A/oro no son columnas de ancho fijo (ver layout.py), así que se
    agrupan los dígitos por componentes conexas: un hueco grande entre
    dígitos separa números distintos, uno chico son dígitos del mismo
    número."""
    if th is None:
        return []
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(stats[i]) for i in range(1, n) if stats[i][4] > 200 and stats[i][0] > 0]
    comps.sort(key=lambda s: s[0])

    groups, current, prev_right = [], [], None
    for x, y, w, h, area in comps:
        gap = (x - prev_right) if prev_right is not None else 0
        if prev_right is not None and gap > gap_threshold:
            groups.append(current)
            current = []
        current.append((x, y, w, h))
        prev_right = x + w
    if current:
        groups.append(current)
    if len(groups) > expect:
        groups = groups[:expect]

    numbers = []
    for g in groups:
        x1 = min(c[0] for c in g)
        x2 = max(c[0] + c[2] for c in g)
        crop = th[:, max(0, x1 - inner_pad):x2 + inner_pad]
        numbers.append(ocr_isolated_number(pad(crop)))
    return numbers


def ocr_rating(image, box):
    """El recorte del rating trae encima parte del ícono decorativo de la
    medalla (corona/laureles), que a veces Tesseract confunde con un dígito
    de más (ej. "9.0" -> "907" -> se leía "90.7"). Se aíslan por componentes
    conexas solo los blobs con forma de dígito/punto (más altos que anchos)
    antes de mandarlo a OCR, descartando la decoración."""
    crop_bgr = layout.crop(image, box)
    th = binarize(crop_bgr, scale=6)
    if th is None:
        return ""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(s) for s in stats[1:] if s[4] > 80]
    # los dígitos y el punto decimal siempre son más altos que anchos (ancho
    # <= alto); la decoración del badge (corona/laureles), sea uno o varios
    # blobs, siempre es más ancha que alta. Un filtro por posición no
    # alcanza porque a veces la decoración se funde con el número en un
    # solo blob grande (ej. cuando el jugador es MVP).
    digit_comps = [c for c in comps if c[2] <= c[3]] or comps
    if not digit_comps:
        return ""
    x1 = min(c[0] for c in digit_comps)
    y1 = min(c[1] for c in digit_comps)
    x2 = max(c[0] + c[2] for c in digit_comps)
    y2 = max(c[1] + c[3] for c in digit_comps)
    digit_crop = th[y1:y2, x1:x2]

    txt = ocr_isolated_number(pad(digit_crop), whitelist="0123456789.")
    txt = txt.strip(".")
    if not txt:
        return ""
    if "." not in txt:
        if len(txt) < 2:
            # un solo dígito suelto sin punto: seguro se perdió una parte
            # del número (ej. el "1" de "10.4" fundido con la decoración
            # de arriba). Mejor no adivinar.
            return ""
        txt = txt[:-1] + "." + txt[-1]
    return txt


def split_stats_block_template(th, gap_threshold=45, expect=4):
    """Igual segmentación que split_stats_block (misma agrupación por
    huecos entre componentes conexas), pero clasificando cada dígito por
    separado contra las plantillas de digit_recognition.py en vez de
    mandarle el grupo entero a Tesseract. Si un solo dígito del grupo no se
    reconoce con confianza, se descarta el número completo antes que
    devolver una lectura parcial/adivinada."""
    if th is None:
        return []
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(stats[i]) for i in range(1, n) if stats[i][4] > 200 and stats[i][0] > 0]
    comps.sort(key=lambda s: s[0])

    groups, current, prev_right = [], [], None
    for x, y, w, h, area in comps:
        gap = (x - prev_right) if prev_right is not None else 0
        if prev_right is not None and gap > gap_threshold:
            groups.append(current)
            current = []
        current.append((x, y, w, h))
        prev_right = x + w
    if current:
        groups.append(current)
    if len(groups) > expect:
        groups = groups[:expect]

    numbers = []
    for g in groups:
        chars = []
        for x, y, w, h in sorted(g, key=lambda c: c[0]):
            digito = digitrec.identificar_digito(pad(th[y:y + h, x:x + w]))
            if digito is None:
                chars = None
                break
            chars.append(digito)
        numbers.append("".join(chars) if chars else "")
    return numbers


def ocr_mvp(image, box) -> bool:
    th = binarize(layout.crop(image, box), scale=4)
    if th is None:
        return False
    txt = ocr_text(pad(th, 15), psm=6).upper()
    return "MVP" in txt


def ocr_header_number(image, box):
    """El marcador (score) a veces trae encima una franja diagonal
    decorativa del banner VICTORY/DEFEAT que Tesseract suma al dígito y lo
    deforma (ej. "15" -> "45"). Igual que en ocr_rating, se aíslan por
    componentes conexas solo los blobs grandes (los dígitos reales son
    mucho más grandes que cualquier resto de decoración) antes de OCR."""
    th = binarize(layout.crop(image, box), scale=4)
    if th is None:
        return ""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(s) for s in stats[1:] if s[4] > 100]
    if not comps:
        return ""
    max_area = max(c[4] for c in comps)
    digit_comps = [c for c in comps if c[4] > max_area * 0.4]
    x1 = min(c[0] for c in digit_comps)
    y1 = min(c[1] for c in digit_comps)
    x2 = max(c[0] + c[2] for c in digit_comps)
    y2 = max(c[1] + c[3] for c in digit_comps)
    digit_crop = th[y1:y2, x1:x2]
    return ocr_isolated_number(pad(digit_crop))


def ocr_rating_template(image, box):
    """Igual segmentación/filtro de decoración que ocr_rating, pero
    clasificando cada dígito por separado contra las plantillas en vez de
    Tesseract. El punto decimal se detecta por tamaño relativo (ver
    digitrec.es_punto_decimal), no hay plantilla de punto porque no se
    minaron muestras confiables de ese carácter."""
    crop_bgr = layout.crop(image, box)
    th = binarize(crop_bgr, scale=6)
    if th is None:
        return ""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(s) for s in stats[1:] if s[4] > 80]
    digit_comps = [c for c in comps if c[2] <= c[3]] or comps
    if not digit_comps:
        return ""
    digit_comps.sort(key=lambda c: c[0])
    areas = sorted(c[4] for c in digit_comps)
    mediana = areas[len(areas) // 2]

    chars = []
    for x, y, w, h, area in digit_comps:
        if digitrec.es_punto_decimal(w, h, area, mediana):
            chars.append(".")
            continue
        digito = digitrec.identificar_digito(pad(th[y:y + h, x:x + w]))
        if digito is None:
            return ""
        chars.append(digito)

    txt = "".join(chars).strip(".")
    if not txt:
        return ""
    if "." not in txt:
        if len(txt) < 2:
            return ""
        txt = txt[:-1] + "." + txt[-1]
    return txt


def ocr_header_number_template(image, box):
    """Igual segmentación/filtro de decoración que ocr_header_number, pero
    clasificando cada dígito por separado contra las plantillas."""
    th = binarize(layout.crop(image, box), scale=4)
    if th is None:
        return ""
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    comps = [tuple(s) for s in stats[1:] if s[4] > 100]
    if not comps:
        return ""
    max_area = max(c[4] for c in comps)
    digit_comps = sorted((c for c in comps if c[4] > max_area * 0.4), key=lambda c: c[0])

    chars = []
    for x, y, w, h, area in digit_comps:
        digito = digitrec.identificar_digito(pad(th[y:y + h, x:x + w]))
        if digito is None:
            return ""
        chars.append(digito)
    return "".join(chars)


def ocr_rating_hibrido(image, box):
    """Plantilla primero (más confiable, ver digit_recognition.py); si no
    está segura (devuelve ""), cae a Tesseract — nunca peor que antes."""
    resultado = ocr_rating_template(image, box)
    return resultado if resultado else ocr_rating(image, box)


def ocr_header_number_hibrido(image, box):
    resultado = ocr_header_number_template(image, box)
    return resultado if resultado else ocr_header_number(image, box)


def split_stats_block_hibrido(th):
    """Compara campo por campo (K/D/A/oro): usa la lectura por plantilla
    si es confiable, y si no cae a la de Tesseract para ESE campo puntual
    (no todo el bloque), porque la confianza de cada número es
    independiente del resto."""
    nuevos = split_stats_block_template(th)
    viejos = split_stats_block(th)
    combinados = []
    for i in range(max(len(nuevos), len(viejos))):
        nuevo = nuevos[i] if i < len(nuevos) else ""
        viejo = viejos[i] if i < len(viejos) else ""
        combinados.append(nuevo if nuevo else viejo)
    return combinados


def clean_name(raw: str) -> str:
    """Del lado rojo el recorte de nombre es ancho a propósito (para no
    cortar nombres largos) y a veces pisa la cola del bloque de stats
    vecino, colando dígitos sueltos antes del nombre real (ej. "3 7 2
    AkihikoYoshida"). Un nombre real de MLBB nunca arranca con una racha de
    tokens sin ninguna letra adentro, así que se descartan."""
    tokens = raw.split()
    while tokens and not any(c.isalpha() for c in tokens[0]):
        tokens.pop(0)
    return " ".join(tokens)


# El tag de clan se renderiza en dorado, bien distinto del color del
# nombre real (celeste en el equipo azul, rosado en el rojo) — confirmado
# con un histograma de Hue sobre cientos de recortes reales (H≈10-33 para
# el dorado, sin superponerse con ningún color de nombre PROMEDIO). Tres
# intentos de aprovechar esto se probaron y se revirtieron, cada uno con
# una falla distinta al validar contra las 25 capturas reales:
#   1. Pintar esos píxeles de negro antes de OCR: le rompe a EasyOCR la
#      continuidad visual y arruina también la lectura de letras vecinas.
#   2. Recortar el ancho de la imagen hasta el borde del dorado: generaliza
#      bien a tags que la lista curada no conoce ("RRQ", "KOT", "NXG"), pero
#      el punto de corte a veces caía encima de la primera letra real y la
#      arruinaba ("DLABLO" -> ")LABLO") — el difuminado entre tag y nombre
#      hacía que "el final del dorado" no fuera un límite seguro.
#   3. Recortar donde EMPIEZA el texto real (no donde termina el dorado):
#      evitó la falla del intento 2, pero reveló un problema de fondo, no
#      de calibración: algunos jugadores decoran su propio nombre con
#      símbolos (ej. "†Rodri", un puntito antes de "Girl...") cuyo
#      antialiasing cae en el MISMO rango de tono/saturación que un tag de
#      clan real (medido: ambos casos rondan H≈20-22, S hasta ~150-170) —
#      no hay umbral de color que los separe, así que el heurístico les
#      comía la primera letra real a esos nombres ("Girl" -> "Sirl").
# Con tres fallas distintas confirmadas, se descartó el color como método
# principal. Queda la lista curada de TAGS_DE_CLAN_CONOCIDOS de abajo +
# el corte determinístico por username propio, sin ninguna de estas fallas
# (validados sin regresiones). Si se retoma en el futuro, la señal de color
# por sí sola no alcanza — haría falta algo más (ej. posición/tamaño
# esperado del tag, o simplemente aceptar que ciertos nombres decorados con
# símbolos cálidos son un caso perdido).


def leer_nombre_hibrido(image, box):
    """EasyOCR primero (más robusto con símbolos/clanes estilizados que
    Tesseract, ver name_recognition.py); si no está seguro, cae al recorte
    binarizado + Tesseract de siempre — nunca peor que antes."""
    crop_bgr = layout.crop(image, box)
    texto, confianza = namerec.leer_nombre(crop_bgr)
    if confianza >= 0.4 and texto.strip():
        return clean_name(texto)
    return clean_name(ocr_text(binarize(crop_bgr, scale=3)))


def best_name_match_ratio(username: str, ocr_name: str) -> float:
    """Similitud difusa entre el username configurado y un nombre leído por
    OCR. Hace falta ser tolerante: el OCR de nombres estilizados con
    símbolos/clanes suele arrastrar ruido (ej. 'STpipa' -> 'ES!pipa'), así
    que un substring exacto no siempre alcanza."""
    name = ocr_name.lower()
    if username in name:
        return 1.0
    return difflib.SequenceMatcher(None, username, name).ratio()


def read_row(image, row_index: int, side: str) -> dict:
    boxes = layout.get_row_boxes(row_index, side)
    name = leer_nombre_hibrido(image, boxes["name"])

    stats_th = binarize(layout.crop(image, boxes["stats"]))
    nums = split_stats_block_hibrido(stats_th)
    if side == "blue":
        k, d, a, gold = (nums + [""] * 4)[:4]
    else:
        # el bloque viene como "Gold K D A" -> reordenar a K D A Gold
        nums = (nums + [""] * 4)[:4]
        gold, k, d, a = nums

    rating = ocr_rating_hibrido(image, boxes["badge_number"])
    mvp = ocr_mvp(image, boxes["badge_icon"])

    return {
        "name": name,
        "kills": k,
        "deaths": d,
        "assists": a,
        "gold": gold,
        "rating": rating,
        "mvp": mvp,
    }


def layout_parece_valido(header: dict) -> tuple[bool, str]:
    """VICTORY/DEFEAT es texto grande, de alto contraste y vocabulario
    cerrado — sobre las 24 partidas reales procesadas hasta ahora, este
    campo nunca salió con ruido de OCR (ver CLAUDE.md). Si el recorte de
    layout.RESULT_TEXT_BOX no da ninguna de las dos palabras (ni por
    parecido difuso, por si hay ruido puntual), es la señal más confiable
    de que esta captura no encaja con la calibración de layout.py — otro
    dispositivo, otra versión del juego — en vez de solo un dígito mal
    leído. Mejor rechazar la captura entera acá que procesar las 10 filas
    con recortes corridos y guardar datos con confianza pero mal (viola la
    filosofía del proyecto: mejor un dato faltante que uno inventado,
    aplicada ahora a nivel captura completa y no solo campo por campo)."""
    resultado = (header.get("result") or "").upper()
    if "VICTORY" in resultado or "DEFEAT" in resultado:
        return True, ""
    mejor = max(
        difflib.SequenceMatcher(None, resultado, "VICTORY").ratio(),
        difflib.SequenceMatcher(None, resultado, "DEFEAT").ratio(),
    )
    if mejor >= 0.7:
        return True, ""
    return False, f"el texto de resultado leído ('{header.get('result')}') no se parece a VICTORY/DEFEAT"


def read_header(image) -> dict:
    score_left = ocr_header_number_hibrido(image, layout.SCORE_LEFT_BOX)
    score_right = ocr_header_number_hibrido(image, layout.SCORE_RIGHT_BOX)
    result = ocr_text(binarize(layout.crop(image, layout.RESULT_TEXT_BOX), scale=2), psm=7)
    timer = ocr_text(binarize(layout.crop(image, layout.TIMER_BOX), scale=3), psm=7)
    return {
        "score_left": score_left,
        "score_right": score_right,
        "result": result,
        "timer": timer,
    }


def _row_background_brightness(image, row_index: int, side: str) -> float:
    """Franja de fondo lejos de retrato/nombre/stats — antes de x=155 en
    azul, después del ícono de espectador en rojo — para medir brillo puro
    sin que un ítem o texto claro contamine el promedio."""
    top = layout.row_top(row_index)
    x1, x2 = (10, 140) if side == "blue" else (1300, 1360)
    band = layout.crop(image, (x1, int(top), x2, int(top) + 40))
    return float(band.mean()) if band.size else 0.0


def detect_my_row(image) -> tuple[str, int, bool]:
    """MLBB resalta la fila del dueño de la pantalla con una franja de fondo
    notablemente más clara que el resto (~95 de brillo contra ~40-49 de
    cualquier otra fila, medido sobre capturas reales) — siempre del lado
    azul/izquierda, que es como el juego te muestra a vos mismo sin importar
    el color de equipo real de esa partida. Es mucho más confiable que
    emparejar por nombre: no depende de que el nick en pantalla se parezca
    al configurado, lo cual falla justo en los casos que más importan (nicks
    con símbolos/clanes raros, o -en una cuenta web- un usuario que ni
    siquiera coincide con el nick real del jugador).
    Devuelve (lado, fila, confiable) — si el margen contra la segunda fila
    más clara es chico, confiable=False y el llamador debería recurrir al
    matching por nombre como respaldo."""
    candidatos = [
        (side, row, _row_background_brightness(image, row, side))
        for side in ("blue", "red")
        for row in range(layout.NUM_ROWS)
    ]
    candidatos.sort(key=lambda c: c[2], reverse=True)
    (mejor_lado, mejor_fila, mejor_val) = candidatos[0]
    segundo_val = candidatos[1][2]
    confiable = (mejor_val - segundo_val) > 20
    return mejor_lado, mejor_fila, confiable


def _quitar_tag_propio(rows_blue: list, rows_red: list, username: str) -> None:
    """Para tu propia fila alcanza con encontrar dónde aparece el username
    configurado (config.json) dentro del nombre leído y descartar todo lo
    de antes — no hace falta adivinar el tag, ya sabemos exactamente qué
    buscar. A diferencia de _quitar_tags_de_clan (heurística, puede no
    detectar nada si la evidencia en esa partida puntual es débil), esto es
    determinístico: siempre funciona sin importar cómo haya leído el OCR el
    tag ese día."""
    username_compacto = username.replace(" ", "").lower()
    if len(username_compacto) < 3:
        return
    for fila in rows_blue + rows_red:
        nombre = fila["name"]
        if not nombre:
            continue
        compacto = nombre.replace(" ", "").lower()
        idx = compacto.find(username_compacto)
        if idx <= 0:
            continue
        # traducir el índice del string SIN espacios de vuelta al string
        # CON espacios, para no perder/correr separadores al recortar.
        restantes, corte = idx, 0
        for ch in nombre:
            if restantes == 0:
                break
            if ch != " ":
                restantes -= 1
            corte += 1
        fila["name"] = clean_name(nombre[corte:])


# Tags de clan confirmados a mano (ver revisión del 2026-07-26). El mismo
# tag real puede salir leído distinto según el OCR ("YF" vs "YES"), así que
# entran las dos variantes. Un primer intento de DETECTARLO estadísticamente
# por co-ocurrencia dentro de una sola partida falló en la mayoría de los
# casos: la confirmación necesitaba encontrar el tag "separado" por un
# espacio al menos una vez en ESA captura puntual, y la mayoría de las veces
# viene pegado al nombre en las 10 filas de esa partida, así que nunca
# juntaba evidencia suficiente. Mantener una lista chica y agregar acá a
# mano cuando aparezca un tag nuevo es más simple y no tiene riesgo de
# recortar por error un nombre real que no tiene ningún tag.
TAGS_DE_CLAN_CONOCIDOS = {"yf", "yes"}


def _quitar_tags_de_clan(rows_blue: list, rows_red: list) -> None:
    """Descarta cualquiera de TAGS_DE_CLAN_CONOCIDOS del principio del
    nombre, con o sin espacio de separación ("YF Gabvriel" -> "Gabvriel",
    "YFSTpipa" -> "STpipa"). No hace falta el tag para saber de quién es
    cada fila (eso ya lo resuelve detect_my_row por brillo), así que se
    descarta directamente en vez de mostrarlo. Modifica rows_blue/rows_red
    in-place."""
    for fila in rows_blue + rows_red:
        nombre = fila["name"]
        if not nombre:
            continue
        for tag in sorted(TAGS_DE_CLAN_CONOCIDOS, key=len, reverse=True):
            partes = nombre.split(" ", 1)
            if len(partes) == 2 and partes[0].lower() == tag:
                fila["name"] = clean_name(partes[1].strip())
                break
            if nombre.lower().startswith(tag) and len(nombre) - len(tag) >= 2:
                fila["name"] = clean_name(nombre[len(tag):])
                break


def extraer_partida(path: str, username: str) -> dict:
    """Lee una captura de post-partida entera: header + las 10 filas de
    jugadores, con el lado 'yo'/'rival' ya resuelto. Devuelve un dict lindo
    para que Fase 5 lo escriba directo a la base."""
    raw = cv2.imread(path)
    if raw is None:
        raise ValueError(f"No se pudo abrir la imagen: {path}")
    image = layout.normalize_to_ref_width(raw)

    header = read_header(image)
    rows_blue = [read_row(image, i, "blue") for i in range(layout.NUM_ROWS)]
    rows_red = [read_row(image, i, "red") for i in range(layout.NUM_ROWS)]
    _quitar_tag_propio(rows_blue, rows_red, username)
    _quitar_tags_de_clan(rows_blue, rows_red)

    my_side, my_row_index, confiable = detect_my_row(image)
    if not confiable:
        blue_ratios = [best_name_match_ratio(username, r["name"]) for r in rows_blue]
        red_ratios = [best_name_match_ratio(username, r["name"]) for r in rows_red]
        blue_best = max(blue_ratios)
        red_best = max(red_ratios)
        if blue_best >= red_best:
            my_side, my_row_index = "blue", blue_ratios.index(blue_best)
        else:
            my_side, my_row_index = "red", red_ratios.index(red_best)

    return {
        "path": path,
        "header": header,
        "my_side": my_side,
        "my_row_index": my_row_index,
        "rows_blue": rows_blue,
        "rows_red": rows_red,
    }
