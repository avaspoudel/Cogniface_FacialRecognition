import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from tests.support import stub_face_recognition

stub_face_recognition()

import main


class FakeUpload:
    def __init__(self, content: bytes, content_type: str = "image/jpeg") -> None:
        self.content = content
        self.content_type = content_type
        self.closed = False

    async def read(self, size: int) -> bytes:
        return self.content[:size]

    async def close(self) -> None:
        self.closed = True


class HealthEndpointTests(unittest.TestCase):
    def test_health_is_ready_when_secrets_are_configured(self) -> None:
        with patch.dict(os.environ, {
            "FACE_SERVICE_TOKEN": "service-token",
            "FACE_ENCRYPTION_KEY": "encryption-key",
        }, clear=True):
            self.assertEqual(main.health(), {"status": "ok", "ready": True})

    def test_health_reports_missing_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                main.health(),
                {"status": "not_configured", "ready": False},
            )


class ServiceTokenTests(unittest.TestCase):
    def test_valid_service_token_is_accepted(self) -> None:
        with patch.dict(os.environ, {"FACE_SERVICE_TOKEN": "expected"}, clear=True):
            self.assertIsNone(main.require_service_token("expected"))

    def test_invalid_service_token_is_rejected(self) -> None:
        with patch.dict(os.environ, {"FACE_SERVICE_TOKEN": "expected"}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                main.require_service_token("wrong")

        self.assertEqual(raised.exception.status_code, 401)


class ImageUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_jpeg_returns_content_and_closes_upload(self) -> None:
        upload = FakeUpload(b"jpeg-content")

        content = await main.read_jpeg(upload)  # type: ignore[arg-type]

        self.assertEqual(content, b"jpeg-content")
        self.assertTrue(upload.closed)

    async def test_read_jpeg_rejects_non_jpeg_content(self) -> None:
        upload = FakeUpload(b"png-content", "image/png")

        with self.assertRaises(HTTPException) as raised:
            await main.read_jpeg(upload)  # type: ignore[arg-type]

        self.assertEqual(raised.exception.status_code, 415)

    async def test_registration_requires_exact_image_count(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await main.register_face([])

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn(str(main.REGISTRATION_IMAGE_COUNT), raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
