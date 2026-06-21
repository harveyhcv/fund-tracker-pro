"""
AES-256-GCM encryption layer — Fund Tracker Pro
Master key:   ENCRYPTION_KEY env var (any string → SHA-256 → 32 bytes)
Per-user key: HKDF-SHA256(master_key, per-user enc_salt)

Usage:
    from crypto import get_master_key, derive_user_key, encrypt_decimal, decrypt_decimal
"""
import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    _OK = True
except ImportError:
    _OK = False
    logger.warning("cryptography not installed — AES-256-GCM unavailable (pip install cryptography)")


def is_available() -> bool:
    return _OK


def get_master_key() -> "bytes | None":
    """Read ENCRYPTION_KEY env var, hash to 32 bytes. None if not set."""
    val = os.environ.get("ENCRYPTION_KEY", "").strip()
    if not val:
        return None
    return hashlib.sha256(val.encode()).digest()


def derive_user_key(master_key: bytes, enc_salt: bytes) -> bytes:
    """HKDF-SHA256(master_key, enc_salt) → 32-byte per-user key."""
    if not _OK:
        raise RuntimeError("cryptography library not installed")
    hkdf = HKDF(
        algorithm=_hashes.SHA256(),
        length=32,
        salt=enc_salt,
        info=b"ftp-enc-v1",
    )
    return hkdf.derive(master_key)


def make_auth_hash(telegram_id: int, master_key: bytes) -> bytes:
    """HMAC-SHA256(master_key, str(telegram_id)) — identity proof without plaintext storage."""
    return hmac.new(master_key, str(telegram_id).encode(), hashlib.sha256).digest()


# ─── Low-level encrypt / decrypt ────────────────────────────────────────────

def encrypt(data: bytes, key: bytes) -> bytes:
    """AES-256-GCM. Output: 12-byte random nonce ‖ ciphertext+tag (16-byte overhead)."""
    if not _OK:
        raise RuntimeError("cryptography library not installed")
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt(blob: bytes, key: bytes) -> bytes:
    """Inverse of encrypt. Raises InvalidTag on tampered data."""
    if not _OK:
        raise RuntimeError("cryptography library not installed")
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


# ─── Typed helpers ──────────────────────────────────────────────────────────

def encrypt_decimal(value: float, key: bytes) -> bytes:
    """Encrypt a float as its 6-decimal-place string representation."""
    return encrypt(f"{value:.6f}".encode(), key)


def decrypt_decimal(blob: bytes, key: bytes) -> float:
    return float(decrypt(blob, key).decode())


def encrypt_str(text: str, key: bytes) -> bytes:
    return encrypt(text.encode("utf-8"), key)


def decrypt_str(blob: bytes, key: bytes) -> str:
    return decrypt(blob, key).decode("utf-8")
