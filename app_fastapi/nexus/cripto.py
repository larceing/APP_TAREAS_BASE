# -*- coding: utf-8 -*-
"""Cifrado de credenciales por proyecto: AES-256-GCM con clave derivada de la
contrasena via PBKDF2-HMAC-SHA256. La contrasena en si nunca se guarda ni se
usa como clave directamente -- se deriva una clave nueva cada vez, con un salt
unico por credencial, para que probar contrasenas sea deliberadamente lento.

Copia literal de APP_NEXUS_BUSCADOR/app/cripto.py, sin cambios.

Formato guardado en `credenciales.valor` (base64 de la concatenacion, texto
plano en la columna pero ilegible sin la contrasena):
    salt (16 bytes) + nonce (12 bytes) + tag (16 bytes) + ciphertext
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PBKDF2_ITERATIONS = 200_000
SALT_LEN = 16
NONCE_LEN = 12


def _derivar_clave(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32)


def cifrar(password: str, secreto: str) -> str:
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    clave = _derivar_clave(password, salt)
    ciphertext_con_tag = AESGCM(clave).encrypt(nonce, secreto.encode("utf-8"), None)
    blob = salt + nonce + ciphertext_con_tag
    return base64.b64encode(blob).decode("ascii")


def descifrar(password: str, valor_b64: str) -> str | None:
    """Devuelve el secreto en claro, o None si la contrasena es incorrecta
    (o el dato esta corrupto) -- AES-GCM falla la verificacion en ese caso,
    no descifra basura en silencio."""
    try:
        blob = base64.b64decode(valor_b64)
        salt, nonce, ciphertext_con_tag = blob[:SALT_LEN], blob[SALT_LEN:SALT_LEN + NONCE_LEN], blob[SALT_LEN + NONCE_LEN:]
        clave = _derivar_clave(password, salt)
        secreto = AESGCM(clave).decrypt(nonce, ciphertext_con_tag, None)
        return secreto.decode("utf-8")
    except Exception:
        return None
