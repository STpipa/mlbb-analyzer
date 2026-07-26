"""
Fase 9: recuperación de contraseña. El proyecto no tiene servidor de email,
así que el reseteo lo hace quien administra el host (acceso directo a la
máquina/base) en vez de un flujo de "olvidé mi contraseña" por mail.

Uso: python src/reset_password.py <usuario>
Pide la contraseña nueva de forma interactiva (no queda en el historial de
la terminal).
"""
import getpass
import sys

import auth
import database as db


def main(username: str) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_username(conn, username)
    if user is None:
        print(f"No existe ningún usuario '{username}'.")
        sys.exit(1)

    password = getpass.getpass("Contraseña nueva: ")
    confirm = getpass.getpass("Repetila: ")
    if password != confirm:
        print("No coinciden, no se cambió nada.")
        sys.exit(1)
    if len(password) < 4:
        print("Muy corta (mínimo 4 caracteres), no se cambió nada.")
        sys.exit(1)

    db.set_password(conn, user[0], auth.hash_password(password))
    conn.close()
    print(f"Contraseña de '{username}' actualizada.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python src/reset_password.py <usuario>")
        sys.exit(1)
    main(sys.argv[1])
