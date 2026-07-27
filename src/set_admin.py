"""
Fase 10: otorgar o quitar el rol de administrador a una cuenta. A propósito
no hay forma de hacer esto desde la web (mismo criterio que
reset_password.py) — es una acción de quien tiene acceso directo al host,
no algo que una cuenta pueda otorgarse a sí misma.

Uso:
  python src/set_admin.py <usuario>          # otorga admin
  python src/set_admin.py <usuario> quitar   # quita admin
"""
import sys

import database as db


def main(username: str, quitar: bool) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_username(conn, username)
    if user is None:
        print(f"No existe ningún usuario '{username}'.")
        sys.exit(1)

    db.set_admin(conn, user[0], not quitar)
    conn.close()
    if quitar:
        print(f"'{username}' ya no es administrador.")
    else:
        print(f"'{username}' ahora es administrador.")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "quitar"):
        print("Uso: python src/set_admin.py <usuario> [quitar]")
        sys.exit(1)
    main(sys.argv[1], quitar=len(sys.argv) == 3)
