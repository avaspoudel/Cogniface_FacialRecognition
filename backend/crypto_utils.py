"""
crypto_utils.py

Encryption helpers for facial embeddings at rest, matching:
  - FR-2.1.14: "System shall encrypt facial feature embeddings before storage"
  - NFR-14: Data Encryption

Uses Fernet (AES-128 in CBC mode with an HMAC, from the `cryptography`
package) as a simple, well-audited symmetric scheme suitable for a
capstone project. In a real cloud deployment this key would live in a
managed secret store (AWS KMS / Secrets Manager, Azure Key Vault, etc.)
rather than a local file -- that swap is called out below.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

KEY_PATH = Path(__file__).parent / "storage" / "encryption.key"


def _load_or_create_key() -> bytes:
    """
    Load the Fernet key from disk, generating one on first run.

    PRODUCTION NOTE: swap this for a fetch from a managed secret store
    (e.g. AWS Secrets Manager / KMS) so the key is never written to the
    application's own filesystem or checked into source control.
    """
    env_key = os.environ.get("FACE_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()

    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()

    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    os.chmod(KEY_PATH, 0o600)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_embedding(embedding: np.ndarray) -> bytes:
    """Serialize a float embedding vector and encrypt it for storage."""
    raw = np.asarray(embedding, dtype=np.float64).tobytes()
    return _fernet.encrypt(raw)


def decrypt_embedding(token: bytes, dims: int = 128) -> np.ndarray:
    """Decrypt bytes back into a float64 embedding vector."""
    try:
        raw = _fernet.decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Facial data could not be decrypted (bad key or corrupt record)") from exc
    arr = np.frombuffer(raw, dtype=np.float64)
    if dims and arr.shape[0] != dims:
        raise ValueError(f"Decrypted embedding has unexpected shape: {arr.shape}")
    return arr
