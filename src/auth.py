"""
Fase 9: hashing de contraseñas. PBKDF2-HMAC-SHA256 con salt propio por
usuario — no hace falta una librería como bcrypt para el tamaño de este
proyecto, y evita sumar una dependencia nueva solo para esto.
"""
import hashlib
import secrets

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split("$")
    except (ValueError, AttributeError):
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return secrets.compare_digest(check.hex(), digest_hex)
