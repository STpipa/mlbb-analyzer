# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python pipeline + web dashboard that reads Mobile Legends: Bang Bang (MLBB)
post-game screenshots and turns them into structured match history: OCR for
stats (K/D/A, gold, rating, score, MVP), perceptual-hash icon matching for
hero/items, a SQLite database, an Excel export, and an LLM coaching writeup
per match. All comments and CLI output in the codebase are in Spanish
(Argentine Spanish/rioplatense) — match that register when editing.

No git repo is initialized. No automated test suite, linter, or build step
exists; verification is done by running the scripts against real screenshots
and spot-checking output (`calibrate.py`, `recognize_icons.py`, or manual DB
queries), not by unit tests.

## Stack

- **Backend / pipeline**: Python 3, plain scripts (no app framework) for OCR
  and icon-recognition processing.
- **Computer vision / OCR**: OpenCV, Pillow, `pytesseract` (wraps the
  Tesseract OCR binary), `imagehash` (perceptual hashing for icons).
- **Data**: SQLite (`data/db/mlbb.db`), `pandas` + `openpyxl` for the Excel
  export.
- **Web dashboard**: FastAPI + Uvicorn, server-rendered Jinja2 templates
  (`templates/`) + Chart.js via CDN — no SPA framework, no JS build step,
  no Node toolchain in this repo at all.
- **LLM**: `anthropic` SDK, `claude-sonnet-5`, for the per-match coaching
  writeup.
- **Not present**: no Expo, no React Native, no mobile app code of any kind
  currently lives in this repo — if a mobile companion app gets started
  later, it belongs in its own project/section, not folded into this one's
  description.

## Setup

- Python venv at `venv/` (Windows). Activate or call binaries directly:
  `.\venv\Scripts\python.exe`, `.\venv\Scripts\pip.exe`.
- Dependencies: `pip install -r requirements.txt`.
- **External dependency**: Tesseract OCR must be installed separately and on
  PATH (Windows default install: `C:\Program Files\Tesseract-OCR`). Run
  `python src/check_setup.py` to verify Tesseract + all Python deps are wired
  up correctly (Fase 0).
- `config.json` at repo root holds `{"mlbb_username": "..."}` — the in-game
  name used to auto-detect which of the 10 player rows in a screenshot is
  "you" (fuzzy-matched, see `ocr_extraction.best_name_match_ratio`). This is
  also used as the identity for the single local/CLI user (see Multi-user
  section below).
- `ANTHROPIC_API_KEY` env var is required for the coaching feature
  (`analizar_partida.py` / the "Generar análisis" button in the dashboard).

## Common commands

Run everything from the repo root; scripts assume `src/` is the working
directory context via the venv's own site paths, invoked as `python src/<script>.py`.

```
python src/check_setup.py         # Fase 0: verify Tesseract/OpenCV/etc. are wired up
python src/update_reference.py    # download hero/item icon reference art from the wiki
python src/update_knowledge.py    # download hero/item stat data from the wiki (for the coach)
python src/calibrate.py           # print OCR output for data/samples/*, for eyeballing layout.py coordinates
python src/recognize_icons.py     # print icon-recognition results for data/samples/*
python src/procesar.py            # daily use: process new screenshots in data/screenshots/ into the DB
python src/revisar_iconos.py      # INTERACTIVE — manually confirm ambiguous icon matches from data/review/
python src/exportar_excel.py      # export the whole DB to data/exports/mlbb_analysis.xlsx
python src/analizar_partida.py [match_id]   # generate the AI coaching writeup (last match if id omitted)
python src/reset_password.py <username>     # INTERACTIVE — admin-side password reset for the web login
uvicorn webapp:app --app-dir src --reload   # run the web dashboard on http://localhost:8000
```

`revisar_iconos.py` and `reset_password.py` read from stdin interactively
(`input()` / `getpass`) — they must be run in a real terminal by a human,
they will hang or error under a non-interactive/piped invocation.

## Architecture

### Pipeline phases (numbered in Spanish as "Fase N" in module docstrings)

The processing pipeline is linear and each phase's module can be read
independently, but they compose in this order for a single screenshot:

1. **`layout.py`** — hardcoded pixel coordinates for every field (name, K/D/A,
   items, portrait, badge, header score/timer) on a screenshot *normalized to
   `REF_WIDTH=1366`* (`normalize_to_ref_width` rescales by width only,
   preserving aspect ratio — see the module docstring for why height is not
   forced). All coordinates were empirically calibrated (including with
   `cv2.HoughCircles` for the item-icon grid, since the true icon pitch is
   ~49-50px, not an even 40px) and are fragile to any UI/resolution change —
   if a new phone/game-version capture doesn't match, expect systematic
   crop-boundary bugs (icons blending into neighbors, name boxes catching an
   adjacent icon or stray digits) before OCR/recognition bugs. `BLUE` and
   `RED` dicts hold the two team-column layouts; `get_row_boxes(row_index,
   side)` offsets them per row via `ROW_TOPS`.
2. **`ocr_extraction.py`** — Tesseract-based reading of every text/number
   field, using `layout.py`'s boxes. Numeric fields go through
   `ocr_isolated_number` (tries psm 8/7/10 in that order — this exact order
   matters, see "Known OCR quirks" below) after connected-components
   filtering to strip UI decoration that bleeds into the crop (crown/laurel
   graphics on the rating badge, a diagonal banner stripe on the header
   score). `extraer_partida()` is the entry point: reads the whole screenshot
   and resolves which row is "yo" via fuzzy name matching against the
   configured username.
3. **`icon_recognition.py`** — hero/item identification via perceptual hash
   (`imagehash.phash`) + Hamming distance, tried against a small grid of
   pixel-offset/scale variants per icon (phash is very sensitive to a few
   pixels of misalignment). Two reference sources are combined: wiki art in
   `data/reference/heroes|items/` (from `update_reference.py`) and a growing
   corpus of real confirmed crops in `data/reference/heroes|items_learned/`
   (grown via `revisar_iconos.py`) — the wiki art alone is not reliable
   enough (Hamming distance to the *correct* wiki icon and to a *wrong* one
   land in overlapping ranges), real learned crops match much better.
   `HERO_THRESHOLD`/`ITEM_THRESHOLD` are intentionally strict; anything above
   threshold becomes `"unknown"` rather than a guessed match, and gets saved
   to `data/review/` with its top-3 nearest candidates encoded in the
   filename for fast manual review.
4. **`database.py`** — SQLite schema (`matches`, `match_players`, `users`).
   `init_db()` runs ALTER TABLE migrations idempotently on every startup
   (no migration files/versioning — the pattern here is: add an `ALTER
   TABLE ... ADD COLUMN` guarded by a `PRAGMA table_info` check). There is no
   rollback/versioning system; when a fix requires re-deriving historical
   data (e.g. a `layout.py` coordinate fix, or a lowered recognition
   threshold), the established pattern is a **full reprocess**: delete
   `data/db/mlbb.db` + the Excel export, move everything back from
   `data/screenshots/procesadas/` to `data/screenshots/`, and rerun
   `procesar.py` — the screenshots are the source of truth, the DB is a
   derived cache.
5. **`procesar.py`** — orchestrates 1-4 for every new file in
   `data/screenshots/`, dedupes by SHA-256 content hash (the phone's
   screenshot tool reuses filenames like "Captura.PNG" across different
   photos, so filename dedup is unreliable), and archives processed files
   into `data/screenshots/procesadas/`.
6. **`exportar_excel.py`** — dumps the full DB to a two-sheet `.xlsx`
   ("Datos crudos" + a per-hero "Resumen"). **Note**: its query is not yet
   scoped by `usuario_id` — it exports all users mixed together.
7. **`analizar_partida.py`** — builds a prompt from one match's full row data
   plus wiki-derived hero/item stats (`data/knowledge/*.json`, from
   `update_knowledge.py`) and calls Claude (`claude-sonnet-5`, thinking
   disabled) for a coaching writeup in Spanish. Saved both to
   `matches.analisis` and `data/analisis/partida_{id}.txt`.
8. **`webapp.py`** — FastAPI dashboard (Jinja2 + Chart.js, templates in
   `templates/`) over the same DB. Routes: `/` (summary + charts + match
   list), `/partida/{id}` (detail + "Generar análisis" button), `/subir`
   (screenshot upload — runs the same `procesar.process_screenshot()` used
   by the CLI), `/login` / `/registro` / `/logout`.

### Multi-user model

Added after the project was single-user for a while, so some seams remain:

- `users` table: `mlbb_username` (lowercased, used both as login identity
  *and* as the OCR name-matching string for "which row is mine"),
  `password_hash` (PBKDF2-HMAC-SHA256 + per-user salt, see `auth.py` — no
  external hashing lib), nullable (accounts created by the CLI path via
  `get_or_create_user()` have no password until claimed).
- `matches.usuario_id` scopes everything; `stats.py` query functions all
  take `usuario_id` and every `webapp.py` route enforces it (including
  checking match ownership before allowing the "Generar análisis" button, to
  block cross-user access by guessing a match id).
- **The CLI path (`procesar.py` run directly) and the web path (`/subir`)
  are two different trust boundaries.** The CLI always resolves its user via
  `config.json`'s `mlbb_username` (whoever has filesystem access is already
  trusted); the web path resolves it from the session. There's no per-user
  `config.json` — a web account's "which row is mine" name is whatever
  string they registered with.
- No password-reset-by-email flow (no mail server) — `reset_password.py` is
  the deliberate admin-side escape hatch, run directly on the host.
- `webapp.get_current_user_id`-style session resolution and
  `MAX_ANALISIS_POR_USUARIO` (a hardcoded cap in `webapp.py`) exist because
  the coaching feature spends the *host's* `ANTHROPIC_API_KEY` on behalf of
  every logged-in user — there's no per-user billing/API-key model.
- Session auth is a signed cookie (`starlette.middleware.sessions`,
  `itsdangerous`), secret persisted in `data/.session_secret` (generated on
  first run, not checked into anything since there's no git repo — treat it
  as a secret if this ever does get version-controlled).

### Known OCR/recognition quirks worth knowing before "fixing" something

- Tesseract's psm mode matters per-crop in inconsistent, sometimes
  contradictory ways (psm 8 sometimes truncates a multi-char crop to one
  char; psm 7/10 sometimes misread specific glyphs like "7" as "1" in this
  game's font). There's no universally-correct psm ordering — the current
  `(8, 7, 10)` first-valid-wins order in `ocr_isolated_number` is a
  deliberately-chosen least-bad tradeoff; a prior attempt at a "try all,
  pick longest" heuristic silently introduced a systematic misread and was
  reverted. If a specific digit is still misread after everything else is
  ruled out, it's likely this glyph-recognition limitation, not a crop
  alignment bug — the long-term fix under consideration is template-matching
  against the game's own digit font (same phash approach as hero/items)
  instead of leaning on generic Tesseract.
- Missing/ambiguous data is *always* left `NULL`/`"unknown"` rather than
  guessed — this shows up as a deliberate design choice throughout
  (recognition thresholds, OCR fallbacks returning `""`, the coaching
  prompt's system instructions telling the model not to invent values for
  fields marked "no reconocido"). Don't add guessing/fallback heuristics to
  "reduce blanks" — that's against the grain of this codebase.

## End-of-session summary (Obsidian)

At the end of each working session on this project, summarize the progress
and decisions made into:

```
C:\Obsidian Vault\proyectos\mobile-legends-app.md
```

Follow that vault's own conventions (its `CLAUDE.md`, at the vault root,
governs this — re-read it if unsure rather than assuming these notes are
exhaustive):

- `[[double-bracket]]` wikilinks for internal references between notes.
- `#tags` (`#proyecto`, plus `#estado/activo` / `#estado/pausado` /
  `#estado/completado` and `#prioridad/alta|media|baja` as relevant).
- Use `templates/proyecto.md` from the vault when the note doesn't exist yet
  instead of freeform structure.
- A `🔗 Relacionado` section at the end linking related notes (e.g. any
  `personas/` note for people mentioned, related `research/` notes).
- Dates in `YYYY-MM-DD`.
- Prioritize clarity and what future-you needs to pick this up again over
  exhaustively logging everything that happened.
