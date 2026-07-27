"""
Encadena los pasos sueltos del "reproceso completo" (la forma establecida
de aplicar en retrospectiva un fix de layout.py, un corpus de referencia
más grande, o cualquier cambio en el pipeline de reconocimiento a las
partidas ya cargadas): backup de la base, borrar DB + export de Excel,
mover las capturas de procesadas/ de vuelta a screenshots/, correr
procesar.py, y comparar contra el arnés de regresión antes y después.

Antes esto eran 4-5 pasos sueltos a mano (fácil olvidarse alguno, o
hacerlos en el orden equivocado); ahora es un solo comando.

Es una operación destructiva sobre data/db/mlbb.db (aunque se hace un
backup antes) — por eso pide confirmación interactiva antes de arrancar.

Uso: python src/reprocesar_todo.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

import backup_db

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "db" / "mlbb.db"
EXPORTS_DIR = ROOT / "data" / "exports"
SCREENSHOTS_DIR = ROOT / "data" / "screenshots"
PROCESSED_DIR = SCREENSHOTS_DIR / "procesadas"
PYTHON = sys.executable


def _correr(script: str) -> int:
    print(f"\n{'=' * 60}\n$ python src/{script}\n{'=' * 60}")
    return subprocess.run([PYTHON, str(ROOT / "src" / script)], cwd=ROOT).returncode


def main():
    if not DB_PATH.exists():
        print("No hay data/db/mlbb.db todavía -- nada que reprocesar (esto es para cuando ya hay partidas cargadas).")
        return

    procesadas = sorted(PROCESSED_DIR.glob("*")) if PROCESSED_DIR.exists() else []
    print("Esto va a:")
    print(f"  1. Hacer un backup de la base actual (data/db/backups/).")
    print(f"  2. Borrar data/db/mlbb.db y data/exports/*.xlsx.")
    print(f"  3. Mover {len(procesadas)} captura(s) de data/screenshots/procesadas/ de vuelta a data/screenshots/.")
    print(f"  4. Correr procesar.py para recargar todo desde cero.")
    print(f"  5. Comparar el resultado contra data/golden/ (golden_check.py) antes y después.")
    respuesta = input("\n¿Confirmás? [s/N]: ").strip().lower()
    if respuesta != "s":
        print("Cancelado, no se tocó nada.")
        return

    print("\nChequeo del arnés de regresión ANTES de reprocesar (por las dudas)...")
    _correr("golden_check.py")

    destino_backup = backup_db.backup()
    print(f"\nBackup guardado en {destino_backup.relative_to(ROOT)}" if destino_backup else "\n(sin backup previo, no había base)")

    DB_PATH.unlink(missing_ok=True)
    if EXPORTS_DIR.exists():
        for xlsx in EXPORTS_DIR.glob("*.xlsx"):
            xlsx.unlink()

    movidas = 0
    if PROCESSED_DIR.exists():
        for path in list(PROCESSED_DIR.glob("*")):
            if path.is_file():
                shutil.move(str(path), str(SCREENSHOTS_DIR / path.name))
                movidas += 1
    print(f"{movidas} captura(s) movida(s) de vuelta a data/screenshots/.")

    codigo = _correr("procesar.py")
    if codigo != 0:
        print(f"\nAVISO: procesar.py terminó con código {codigo}, revisar la salida de arriba.")

    print("\nChequeo del arnés de regresión DESPUÉS de reprocesar...")
    codigo_golden = _correr("golden_check.py")
    if codigo_golden != 0:
        print(
            "\nHay diferencias contra data/golden/baseline.json -- revisalas a mano (¿mejora o "
            "regresión?) antes de correr golden_capture.py para actualizar la referencia."
        )
    else:
        print("\nListo, sin diferencias contra el arnés de regresión.")


if __name__ == "__main__":
    main()
