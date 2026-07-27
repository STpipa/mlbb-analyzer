"""
Backup simple de data/db/mlbb.db antes de cualquier operación de riesgo
(reproceso completo, o simplemente cada corrida de procesar.py). Guarda una
copia con fecha en data/db/backups/ y poda las más viejas, dejando las
últimas MANTENER.

La base se trata como un cache derivable de las capturas en el resto del
proyecto, pero a medida que más gente sube capturas reales (multi-usuario),
perder todo de un plumazo es más doloroso de reconstruir a mano — este
backup es la red de seguridad barata para eso.

Uso: python src/backup_db.py
"""
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "db" / "mlbb.db"
BACKUP_DIR = ROOT / "data" / "db" / "backups"
MANTENER = 10


def _podar() -> None:
    backups = sorted(BACKUP_DIR.glob("mlbb_*.db"), key=lambda p: p.stat().st_mtime)
    for viejo in backups[:-MANTENER]:
        viejo.unlink()


def backup() -> Path | None:
    """Devuelve la ruta del backup nuevo, o None si todavía no hay base
    para respaldar (primera corrida)."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = BACKUP_DIR / f"mlbb_{timestamp}.db"
    shutil.copy2(DB_PATH, destino)
    _podar()
    return destino


if __name__ == "__main__":
    destino = backup()
    if destino:
        print(f"Backup guardado en {destino.relative_to(ROOT)}")
    else:
        print("Todavía no hay base de datos, nada que respaldar.")
