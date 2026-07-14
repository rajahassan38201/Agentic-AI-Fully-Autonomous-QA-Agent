"""RFC 6238 TOTP generation for MFA login testing.

Implemented with the standard library so we don't need an extra dependency.
Given the account's base32 shared secret (the same string a authenticator app
is seeded with), `generate_totp` returns the current 6-digit code.
"""
import base64
import hashlib
import hmac
import struct
import time


def generate_totp(secret: str, digits: int = 6, period: int = 30) -> str:
    """Return the current TOTP code for a base32 secret.

    Raises ValueError if the secret is empty or not valid base32.
    """
    if not secret:
        raise ValueError("empty secret")

    # Authenticator secrets are usually shown with spaces and no padding.
    normalized = secret.replace(" ", "").upper()
    normalized += "=" * (-len(normalized) % 8)  # restore base32 padding
    key = base64.b32decode(normalized, casefold=True)

    counter = int(time.time()) // period
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()

    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)
