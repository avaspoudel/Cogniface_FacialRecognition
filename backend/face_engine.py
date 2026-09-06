"""Database- and HTTP-independent facial-recognition operations."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import face_recognition
import numpy as np

MINIMUM_IMAGE_QUALITY = 50.0
FACE_DETECTION_MODEL = "hog"
MIN_FACE_SIZE_RATIO = 0.12

FaceLocation = tuple[int, int, int, int]


@dataclass
class QualityReport:
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= MINIMUM_IMAGE_QUALITY and not self.reasons


class FaceEngineError(Exception):
    """Raised when an image cannot be decoded or embedded."""


def decode_image_bytes(raw: bytes) -> np.ndarray:
    """Decode binary JPEG data into an RGB image."""
    if not raw:
        raise FaceEngineError("Image is empty")

    encoded = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if bgr is None:
        raise FaceEngineError("Image bytes are not a valid JPEG")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def detect_faces(
    image: np.ndarray,
    model: str = FACE_DETECTION_MODEL,
) -> list[FaceLocation]:
    """Return face boxes as `(top, right, bottom, left)` tuples."""
    if image is None or image.size == 0:
        raise FaceEngineError("Cannot detect faces in an empty image")
    return face_recognition.face_locations(image, model=model)


def assess_image_quality(
    image: np.ndarray,
    face_location: FaceLocation,
) -> QualityReport:
    """Evaluate sharpness, brightness, and face size for registration."""
    reasons: list[str] = []
    top, right, bottom, left = face_location
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    laplacian_variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_score = float(np.clip(laplacian_variance / 150.0 * 100, 0, 100))
    if blur_score < 35:
        reasons.append("Image appears blurry")

    mean_brightness = float(gray.mean())
    if mean_brightness < 40:
        brightness_score = mean_brightness / 40.0 * 100
        reasons.append("Image is too dark")
    elif mean_brightness > 210:
        brightness_score = max(0.0, (255 - mean_brightness) / 45.0 * 100)
        reasons.append("Image is too bright / overexposed")
    else:
        brightness_score = 100.0
    brightness_score = float(np.clip(brightness_score, 0, 100))

    face_height = max(0, bottom - top)
    face_width = max(0, right - left)
    shorter_side = min(height, width)
    size_ratio = min(face_height, face_width) / shorter_side if shorter_side else 0.0
    size_score = float(np.clip(size_ratio / MIN_FACE_SIZE_RATIO * 100, 0, 100))
    if size_ratio < MIN_FACE_SIZE_RATIO:
        reasons.append("Face is too small / too far from camera")

    score = 0.4 * blur_score + 0.3 * brightness_score + 0.3 * size_score
    return QualityReport(score=round(score, 1), reasons=reasons)


def assess_face_pose(
    image: np.ndarray,
    face_location: FaceLocation,
) -> list[str]:
    """Reject a pose that is too extreme for a reliable template."""
    landmarks = face_recognition.face_landmarks(image, face_locations=[face_location])
    if not landmarks:
        return ["Could not assess face position"]

    points = landmarks[0]
    left_eye = points.get("left_eye", [])
    right_eye = points.get("right_eye", [])
    nose_tip = points.get("nose_tip", [])
    if not left_eye or not right_eye or not nose_tip:
        return ["Could not assess face position"]

    top, right, bottom, left = face_location
    face_width = max(1, right - left)
    face_height = max(1, bottom - top)
    nose_x = float(np.mean([point[0] for point in nose_tip]))
    nose_y = float(np.mean([point[1] for point in nose_tip]))
    reasons: list[str] = []

    if nose_x < left + 0.20 * face_width or nose_x > right - 0.20 * face_width:
        reasons.append("Face is turned too far to the side")
    if nose_y < top + 0.25 * face_height or nose_y > top + 0.80 * face_height:
        reasons.append("Face is tilted too far up or down")
    return reasons


def generate_embedding(
    image: np.ndarray,
    face_location: FaceLocation,
) -> np.ndarray:
    """Generate the 128-dimensional dlib embedding for one face."""
    embeddings = face_recognition.face_encodings(
        image,
        known_face_locations=[face_location],
    )
    if not embeddings:
        raise FaceEngineError("Could not generate an embedding for this face")
    return embeddings[0]


def average_embeddings(embeddings: list[np.ndarray]) -> np.ndarray:
    """Create one representative embedding from accepted registration images."""
    if not embeddings:
        raise FaceEngineError("Cannot average an empty embedding list")
    return np.mean(np.vstack(embeddings), axis=0)


def euclidean_distance(first: np.ndarray, second: np.ndarray) -> float:
    """Return dlib's native face-embedding distance; lower is more similar."""
    return float(np.linalg.norm(np.asarray(first) - np.asarray(second)))


def process_registration_bytes(
    raw: bytes,
) -> tuple[np.ndarray | None, np.ndarray | None, list[str], float | None]:
    """Decode, validate, and embed one registration JPEG."""
    try:
        image = decode_image_bytes(raw)
    except FaceEngineError as exc:
        return None, None, [str(exc)], None

    faces = detect_faces(image)
    if len(faces) == 0:
        return image, None, ["No face detected"], None
    if len(faces) > 1:
        return image, None, ["Multiple faces detected"], None

    face_location = faces[0]
    quality = assess_image_quality(image, face_location)
    if not quality.passed:
        return image, None, quality.reasons or ["Image quality too low"], quality.score

    pose_reasons = assess_face_pose(image, face_location)
    if pose_reasons:
        return image, None, pose_reasons, quality.score

    try:
        embedding = generate_embedding(image, face_location)
    except FaceEngineError as exc:
        return image, None, [str(exc)], quality.score
    return image, embedding, [], quality.score
