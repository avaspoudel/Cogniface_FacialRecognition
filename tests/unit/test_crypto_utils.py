import os
import unittest
from unittest.mock import patch

import numpy as np
from cryptography.fernet import Fernet

import crypto_utils


class EmbeddingEncryptionTests(unittest.TestCase):
    def test_embedding_round_trip(self) -> None:
        embedding = np.linspace(0, 1, 128, dtype=np.float32)

        with patch.dict(os.environ, {"FACE_ENCRYPTION_KEY": Fernet.generate_key().decode()}):
            encrypted = crypto_utils.encrypt_embedding(embedding)
            decrypted = crypto_utils.decrypt_embedding(encrypted)

        np.testing.assert_array_equal(decrypted, embedding)

    def test_missing_key_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FACE_ENCRYPTION_KEY is required"):
                crypto_utils.encrypt_embedding(np.zeros(128, dtype=np.float32))

    def test_unexpected_embedding_shape_is_rejected(self) -> None:
        key = Fernet.generate_key()
        token = Fernet(key).encrypt(np.zeros(4, dtype=np.float32).tobytes())

        with patch.dict(os.environ, {"FACE_ENCRYPTION_KEY": key.decode()}):
            with self.assertRaisesRegex(ValueError, "unexpected shape"):
                crypto_utils.decrypt_embedding(token)


if __name__ == "__main__":
    unittest.main()
