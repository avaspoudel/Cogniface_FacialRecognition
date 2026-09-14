import unittest

import numpy as np

from tests.support import stub_face_recognition

stub_face_recognition()

import face_engine


class FaceEngineMathTests(unittest.TestCase):
    def test_average_embeddings(self) -> None:
        result = face_engine.average_embeddings([
            np.array([0.0, 2.0]),
            np.array([2.0, 4.0]),
        ])

        np.testing.assert_array_equal(result, np.array([1.0, 3.0]))

    def test_average_embeddings_rejects_empty_input(self) -> None:
        with self.assertRaisesRegex(face_engine.FaceEngineError, "empty embedding list"):
            face_engine.average_embeddings([])

    def test_euclidean_distance(self) -> None:
        distance = face_engine.euclidean_distance(
            np.array([0.0, 0.0]),
            np.array([3.0, 4.0]),
        )

        self.assertEqual(distance, 5.0)

    def test_decode_rejects_empty_image(self) -> None:
        with self.assertRaisesRegex(face_engine.FaceEngineError, "Image is empty"):
            face_engine.decode_image_bytes(b"")


if __name__ == "__main__":
    unittest.main()
