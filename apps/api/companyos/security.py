import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from companyos.config import get_settings

_password_hasher = PasswordHasher()
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str) -> str:
    # CSRF token is derived from the session, so nothing extra is stored
    secret = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(secret, f"csrf:{session_token}".encode(), hashlib.sha256).hexdigest()


def csrf_matches(session_token: str, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(csrf_token_for(session_token), provided or "")


class SecretBox:
    """Encrypts tenant secrets at rest; first key encrypts, all keys decrypt (rotation)."""

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise RuntimeError("COMPANYOS encryption key missing: set ENCRYPTION_KEYS in the environment")
        self._fernet = MultiFernet([Fernet(key.encode()) for key in keys])

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as error:
            raise RuntimeError("Stored secret cannot be decrypted with the configured keys") from error


def get_secret_box() -> SecretBox:
    raw = get_settings().encryption_keys.get_secret_value()
    return SecretBox([key.strip() for key in raw.split(",") if key.strip()])


def mask_secret(secret: str) -> str:
    return secret[-4:] if len(secret) >= 8 else "****"
