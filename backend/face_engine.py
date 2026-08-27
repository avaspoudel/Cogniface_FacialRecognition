"""
face_engine.py

Core facial recognition engine for the Cloud-Based Attendance System.

Implements the building blocks used by:
  - Section 5.3 of the proposal: registerStudentFace() pseudocode
  - Section 5.4 of the proposal: processAttendanceFrame() pseudocode

Library choice: `face_recognition` (built on dlib's ResNet-based face
recognition model). It detects faces, produces 128-dimensional face
embeddings, and is fast enough on CPU to meet the NFR-3 latency targets
for a capstone-scale deployment (not thousands of concurrent users).

This module intentionally has NO knowledge of HTTP, databases, or
encryption -- it is a pure "given pixels, do face math" layer, so it can
be unit tested on its own and swapped out later (e.g. for DeepFace or a
cloud vision API) without touching the API layer.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import face_recognition
import numpy as np

# ---------------------------------------------------------------------------
# Tunable constants (mirrors the NFRs / pseudocode in the proposal)
# ---------------------------------------------------------------------------

# FR-2: minimum images required to complete face registration
MIN_REGISTRATION_IMAGES = 15

# Quality gate: images below this score are rejected during registration.
# Score is 0-100, see `assess_image_quality`.
MINIMUM_IMAGE_QUALITY = 50.0

# NFR-3 style recognition threshold used in processAttendanceFrame().
# NOTE: `face_recognition` embeddings were trained/tuned for *Euclidean*
# distance (typical "same person" cutoff is a distance of ~0.6), not
# cosine similarity. We still expose cosine similarity because that is
# what the proposal's pseudocode specifies, but 0.85 is a starting point
# -- calibrate it against your own captured data (see calibrate.py) and
# record whatever value you land on in the NFR-3 test evidence.
RECOGNITION_THRESHOLD = 0.85

# Which dlib detector to use. "hog" is CPU-fast (meets the <400ms
# detection target on typical laptops); "cnn" is more accurate but slow
# without a GPU. Kept as a constant so it's easy to switch for testing.
FACE_DETECTION_MODEL = "hog"

# Faces smaller than this fraction of the frame's shorter side are
# considered too small/far away to trust for registration or recognition.
MIN_FACE_SIZE_RATIO = 0.12


@dataclass
class DetectedFace:
    """A single detected face plus everything derived from it."""

    location: Tuple[int, int, int, int]  # (top, right, bottom, left)
    embedding: Optional[np.ndarray] = None
    quality: Optional["QualityReport"] = None


@dataclass
class QualityReport:
    score: float  # 0-100, higher is better
    blur_score: float
    brightness_score: float
    size_score: float
    reasons: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= MINIMUM_IMAGE_QUALITY and not self.reasons


class FaceEngineError(Exception):
    """Raised for engine-level failures (bad image data, decode errors)."""


# ---------------------------------------------------------------------------
# Step 4.1 / 3: decode + validate incoming images
# ---------------------------------------------------------------------------

def decode_base64_image(data: str) -> np.ndarray:
    """
    Decode a base64-encoded image (optionally a data: URL) into an RGB
    numpy array, as `face_recognition` expects.

    Mirrors pseudocode step 4.1 "DECODE imageData FROM base64 format" /
    step 3 "DECODE imageFrame FROM base64 format".
    """
    if not data:
        raise FaceEngineError("Empty image payload")

    if "," in data[:64] and data[:5].lower() == "data:":
        # Strip a data URL prefix like "data:image/jpeg;base64,...."
        data = data.split(",", 1)[1]

    try:
        raw = base64.b64decode(data, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise FaceEngineError(f"Could not base64-decode image: {exc}") from exc

    if len(raw) == 0:
        raise FaceEngineError("Decoded image is empty")

    arr = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise FaceEngineError("Image bytes are not a valid JPEG/PNG")

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return rgb


# ---------------------------------------------------------------------------
# Step 4.3 / 4.4: face detection
# ---------------------------------------------------------------------------

def detect_faces(image: np.ndarray, model: str = FACE_DETECTION_MODEL) -> List[Tuple[int, int, int, int]]:
    """
    Detect faces in an RGB image. Returns a list of (top, right, bottom,
    left) bounding boxes, as `face_recognition.face_locations` does.

    Mirrors pseudocode "DETECT faces in decodedImage using face
    detection model".
    """
    if image is None or image.size == 0:
        raise FaceEngineError("Cannot detect faces in an empty image")
    return face_recognition.face_locations(image, model=model)


# ---------------------------------------------------------------------------
# Step 4.5: image quality scoring
# ---------------------------------------------------------------------------

def assess_image_quality(image: np.ndarray, face_location: Tuple[int, int, int, int]) -> QualityReport:
    """
    Score how usable a captured face image is for registration.

    Combines three signals into a 0-100 score:
      - blur (Laplacian variance): rejects motion-blurred / out-of-focus shots
      - brightness (mean pixel intensity): rejects too-dark/blown-out shots
      - face size relative to frame: rejects faces that are too small/far

    Mirrors pseudocode "CALCULATE imagequality OF decodedImage".
    """
    reasons: List[str] = []
    top, right, bottom, left = face_location
    h, w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # --- Blur: variance of the Laplacian. Low variance == blurry. ---
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_score = float(np.clip(laplacian_var / 150.0 * 100, 0, 100))
    if blur_score < 35:
        reasons.append("Image appears blurry")

    # --- Brightness: mean intensity, penalize too dark or too bright. ---
    mean_brightness = float(gray.mean())
    # Ideal band is roughly 60-190 out of 255.
    if mean_brightness < 40:
        brightness_score = mean_brightness / 40.0 * 100
        reasons.append("Image is too dark")
    elif mean_brightness > 210:
        brightness_score = max(0.0, (255 - mean_brightness) / 45.0 * 100)
        reasons.append("Image is too bright / overexposed")
    else:
        brightness_score = 100.0
    brightness_score = float(np.clip(brightness_score, 0, 100))

    # --- Face size relative to frame ---
    face_h = max(0, bottom - top)
    face_w = max(0, right - left)
    shorter_side = min(h, w)
    size_ratio = (min(face_h, face_w) / shorter_side) if shorter_side else 0.0
    size_score = float(np.clip(size_ratio / MIN_FACE_SIZE_RATIO * 100, 0, 100))
    if size_ratio < MIN_FACE_SIZE_RATIO:
        reasons.append("Face is too small / too far from camera")

    overall = 0.4 * blur_score + 0.3 * brightness_score + 0.3 * size_score

    return QualityReport(
        score=round(overall, 1),
        blur_score=round(blur_score, 1),
        brightness_score=round(brightness_score, 1),
        size_score=round(size_score, 1),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Step 4.6: embedding generation
# ---------------------------------------------------------------------------

def generate_embedding(image: np.ndarray, face_location: Tuple[int, int, int, int]) -> np.ndarray:
    """
    Generate a 128-dimensional facial embedding for the given face.

    Mirrors pseudocode "GENERATE facial embedding FROM faceRegion".
    """
    encodings = face_recognition.face_encodings(image, known_face_locations=[face_location])
    if not encodings:
        raise FaceEngineError("Could not generate an embedding for this face")
    return encodings[0]


# ---------------------------------------------------------------------------
# Step 6: averaging embeddings from multiple registration images
# ---------------------------------------------------------------------------

def average_embeddings(embeddings: List[np.ndarray]) -> np.ndarray:
    """
    Combine several per-image embeddings captured during registration
    into a single representative embedding for the student.

    Mirrors pseudocode "CALCULATE mean of all embeddings IN
    facialEmbeddings".
    """
    if not embeddings:
        raise FaceEngineError("Cannot average an empty embedding list")
    stacked = np.vstack(embeddings)
    return np.mean(stacked, axis=0)


# ---------------------------------------------------------------------------
# Step 7.3: similarity comparison
# ---------------------------------------------------------------------------

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity between two embeddings, in [-1, 1] (in practice
    close to [0, 1] for face embeddings of the same modality).

    Mirrors pseudocode "CALCULATE cosine similarity BETWEEN
    currentEmbedding AND studentData.embedding".
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def euclidean_distance(a: np.ndarray, b: np.ndarray) -> float:
    """
    Alternative metric: Euclidean distance, which is what the underlying
    dlib model was actually trained against (lower == more similar,
    "same person" is typically < 0.6). Exposed for calibration /
    comparison against the cosine-similarity approach the proposal
    specifies.
    """
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


# ---------------------------------------------------------------------------
# High-level convenience wrapper used by the API layer
# ---------------------------------------------------------------------------

def process_registration_image(raw_base64: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], List[str]]:
    """
    Run one captured image through the full registration pipeline:
    decode -> detect -> validate face count -> quality check -> embed.

    Returns (decoded_image_or_None, embedding_or_None, rejection_reasons).
    An empty `rejection_reasons` list means the image was accepted.
    """
    reasons: List[str] = []
    try:
        image = decode_base64_image(raw_base64)
    except FaceEngineError as exc:
        return None, None, [str(exc)]

    faces = detect_faces(image)
    if len(faces) == 0:
        return image, None, ["No face detected"]
    if len(faces) > 1:
        return image, None, ["Multiple faces detected"]

    face_location = faces[0]
    quality = assess_image_quality(image, face_location)
    if not quality.passed:
        return image, None, quality.reasons or ["Image quality too low"]

    try:
        embedding = generate_embedding(image, face_location)
    except FaceEngineError as exc:
        return image, None, [str(exc)]

    return image, embedding, reasons
