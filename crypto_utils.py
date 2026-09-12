"""Environment-keyed encryption helpers for biometric templates."""

from __future__ import annotations

import os

import numpy as np
from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    key = os.getenv("FACE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("FACE_ENCRYPTION_KEY is required")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("FACE_ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt_embedding(embedding: np.ndarray) -> bytes:
    return _fernet().encrypt(np.asarray(embedding, dtype=np.float32).tobytes())


def decrypt_embedding(token: str | bytes, dims: int = 128) -> np.ndarray:
    encoded = token.encode("ascii") if isinstance(token, str) else token
    try:
        raw = _fernet().decrypt(encoded)
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Facial data could not be decrypted") from exc
    embedding = np.frombuffer(raw, dtype=np.float32)
    if embedding.shape != (dims,):
        raise ValueError("Decrypted embedding has an unexpected shape")
    return embedding
