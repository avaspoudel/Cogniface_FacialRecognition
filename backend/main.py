"""Private, database-free facial-recognition inference service."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from typing import Annotated

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status

import crypto_utils as crypto
import face_engine as engine
from schemas import RecognitionRoster

logger = logging.getLogger("cogniface-inference")

MAX_IMAGE_BYTES = 1_000_000
REGISTRATION_IMAGE_COUNT = 20
MIN_VALID_REGISTRATION_IMAGES = 15
MATCH_MAX_DISTANCE = float(os.getenv("FACE_MATCH_MAX_DISTANCE", "0.60"))
MATCH_AMBIGUITY_MARGIN = float(os.getenv("FACE_MATCH_AMBIGUITY_MARGIN", "0.05"))
INFERENCE_SEMAPHORE = asyncio.Semaphore(max(1, int(os.getenv("FACE_INFERENCE_CONCURRENCY", "2"))))

app = FastAPI(
    title="CogniFace Internal Inference Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def require_service_token(
    supplied: Annotated[str | None, Header(alias="X-Internal-Service-Token")] = None,
) -> None:
    expected = os.getenv("FACE_SERVICE_TOKEN")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Inference service is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal service token")


async def read_jpeg(upload: UploadFile) -> bytes:
    if upload.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only JPEG images are accepted")
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    await upload.close()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image exceeds the 1 MB limit")
    return content


@app.get("/internal/health")
def health() -> dict[str, object]:
    configured = bool(os.getenv("FACE_SERVICE_TOKEN") and os.getenv("FACE_ENCRYPTION_KEY"))
    return {"status": "ok" if configured else "not_configured", "ready": configured}


@app.post("/internal/face/register", dependencies=[Depends(require_service_token)])
async def register_face(
    images: Annotated[list[UploadFile], File(...)],
) -> dict[str, object]:
    if len(images) != REGISTRATION_IMAGE_COUNT:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Exactly {REGISTRATION_IMAGE_COUNT} images are required",
        )

    embeddings: list[np.ndarray] = []
    quality_scores: list[float] = []
    details: list[dict[str, object]] = []

    for index, upload in enumerate(images):
        try:
            content = await read_jpeg(upload)
            async with INFERENCE_SEMAPHORE:
                _, embedding, reasons, quality_score = await asyncio.to_thread(
                    engine.process_registration_bytes,
                    content,
                )
        except (engine.FaceEngineError, HTTPException) as exc:
            reason = exc.detail if isinstance(exc, HTTPException) else str(exc)
            details.append({"index": index, "accepted": False, "reasons": [reason]})
            continue

        accepted = embedding is not None
        details.append({"index": index, "accepted": accepted, "reasons": reasons})
        if accepted:
            embeddings.append(embedding)
            if quality_score is not None:
                quality_scores.append(quality_score)

    if len(embeddings) < MIN_VALID_REGISTRATION_IMAGES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Not enough valid face images. Please replace the rejected photos.",
                "validImageCount": len(embeddings),
                "requiredValidImageCount": MIN_VALID_REGISTRATION_IMAGES,
                "details": details,
            },
        )

    averaged = engine.average_embeddings(embeddings).astype(np.float32)
    encrypted = crypto.encrypt_embedding(averaged)
    return {
        "success": True,
        "encryptedEmbedding": encrypted.decode("ascii"),
        "validImageCount": len(embeddings),
        "rejectedImageCount": len(images) - len(embeddings),
        "meanQualityScore": round(float(np.mean(quality_scores)), 1) if quality_scores else None,
        "details": details,
    }


@app.post("/internal/face/recognize", dependencies=[Depends(require_service_token)])
async def recognize_faces(
    frame: Annotated[UploadFile, File(...)],
    roster: Annotated[str, Form(...)],
) -> dict[str, object]:
    started = time.perf_counter()
    try:
        parsed_roster = RecognitionRoster.model_validate(json.loads(roster))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid recognition roster") from exc

    frame_bytes = await read_jpeg(frame)
    async with INFERENCE_SEMAPHORE:
        image = await asyncio.to_thread(engine.decode_image_bytes, frame_bytes)
        locations = await asyncio.to_thread(engine.detect_faces, image)
    known: list[tuple[str, str, np.ndarray]] = []
    for student in parsed_roster.students:
        try:
            embedding = crypto.decrypt_embedding(student.encrypted_embedding)
        except ValueError:
            logger.warning("Skipping an unreadable face template for an authorized roster member")
            continue
        known.append((student.student_id, student.student_name, embedding))

    proposed: list[dict[str, object]] = []
    for location in locations:
        try:
            async with INFERENCE_SEMAPHORE:
                observed = await asyncio.to_thread(engine.generate_embedding, image, location)
        except engine.FaceEngineError:
            continue

        ranked = sorted(
            (
                (engine.euclidean_distance(observed, embedding), student_id, student_name)
                for student_id, student_name, embedding in known
            ),
            key=lambda candidate: candidate[0],
        )
        if not ranked or ranked[0][0] > MATCH_MAX_DISTANCE:
            continue
        if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < MATCH_AMBIGUITY_MARGIN:
            continue

        distance, student_id, student_name = ranked[0]
        top, right, bottom, left = location
        proposed.append({
            "studentId": student_id,
            "studentName": student_name,
            "distance": round(distance, 4),
            "box": {"top": top, "right": right, "bottom": bottom, "left": left},
        })

    matches: list[dict[str, object]] = []
    assigned_students: set[str] = set()
    for candidate in sorted(proposed, key=lambda item: float(item["distance"])):
        student_id = str(candidate["studentId"])
        if student_id in assigned_students:
            continue
        assigned_students.add(student_id)
        matches.append(candidate)

    return {
        "success": True,
        "frame": {"width": int(image.shape[1]), "height": int(image.shape[0])},
        "facesDetected": len(locations),
        "matches": matches,
        "processingTimeMs": round((time.perf_counter() - started) * 1000, 1),
    }
