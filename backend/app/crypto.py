"""Symmetric encryption for project credentials at rest.

Projects are created once and tested later, so login credentials have to survive
between those two moments. They are encrypted here with Fernet (AES-128-CBC +
HMAC) and only ever decrypted in memory, at the moment a run starts.

The Fernet key is derived from APP_SECRET_KEY so that any passphrase works as a
key. Losing or changing APP_SECRET_KEY makes existing stored credentials
undecryptable — the projects survive, but their credentials must be re-entered.
"""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import APP_SECRET_KEY


class SecretKeyMissing(RuntimeError):
    """Raised when credentials need encrypting but no APP_SECRET_KEY is set."""


_fernet: Optional[Fernet] = None


def _cipher() -> Fernet:
    """Build (once) the Fernet cipher from APP_SECRET_KEY."""
    global _fernet
    if _fernet is None:
        if not APP_SECRET_KEY:
            raise SecretKeyMissing(
                "APP_SECRET_KEY is not set, so credentials cannot be stored securely. "
                "Add it to backend/.env — see .env.example for how to generate one."
            )
        # SHA-256 gives the exact 32 bytes Fernet wants from any passphrase.
        digest = hashlib.sha256(APP_SECRET_KEY.encode("utf-8")).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt(value: Optional[str]) -> Optional[str]:
    """Encrypt a secret for storage. Empty values stay None (nothing to protect)."""
    if value is None or value == "":
        return None
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: Optional[str]) -> Optional[str]:
    """Decrypt a stored secret.

    Returns None for an unset value, and also for a value that cannot be read
    back (wrong or rotated APP_SECRET_KEY). A run then behaves as if the
    credential were missing rather than crashing the worker thread.
    """
    if not token:
        return None
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, SecretKeyMissing):
        return None


def is_configured() -> bool:
    """Whether credential encryption is available."""
    return bool(APP_SECRET_KEY)
