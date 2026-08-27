"""
main.py

FastAPI service for the facial recognition part of the Cloud-Based
Attendance System capstone project.

Endpoints implement, as closely as practical:
  - FR-2 (Face Registration)      -> POST /api/face/register
  - FR-6.1 (Start attendance)     -> POST /api/attendance/sessions
  - FR-6.2 (Automated recognition)-> POST /api/attendance/frame
  - FR-6.3 (Close session)        -> POST /api/attendance/sessions/{id}/close
  - FR-6.4 (Manual marking)       -> PATCH /api/attendance/sessions/{id}/manual
  - FR-6.5 (Student view)         -> GET  /api/attendance/students/{id}
  - FR-6.6 (Lecturer report)      -> GET  /api/attendance/classes/{id}/report

Run with:
    uvicorn main:app --reload --port 8000

Then open http://127.0.0.1:8000/docs for interactive Swagger UI, or
serve the frontend/ folder and point it at this API.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import crypto_utils as cu
import database as db
import face_engine as fe
from schemas import (
    ClassCreate,
    EnrollRequest,
    FaceRegistrationRequest,
    FrameRequest,
    ManualAttendanceUpdate,
    SessionStartRequest,
    StudentCreate,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("attendance-api")

FACE_IMAGE_DIR = Path(__file__).parent / "storage" / "face_images"

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    FACE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Database ready at %s", db.DB_PATH)
    yield


app = FastAPI(
    title="Attendance System - Facial Recognition API",
    description="Face registration and face-recognition-based attendance, per FR-2 and FR-6.",
    version="0.1.0",
    lifespan=lifespan,
)

# Dev-friendly CORS so a locally served frontend (any port) can call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@app.post("/api/students", status_code=201)
def create_student(payload: StudentCreate):
    if db.get_student(payload.student_id) is not None:
        raise HTTPException(409, f"Student {payload.student_id} already exists")
    db.create_student(payload.student_id, payload.name, payload.email)
    return dict(db.get_student(payload.student_id))


@app.get("/api/students")
def list_students():
    return [dict(r) for r in db.list_students()]


@app.get("/api/students/{student_id}")
def get_student(student_id: str):
    student = db.get_student(student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    return dict(student)


# ---------------------------------------------------------------------------
# Classes / enrollment (minimal scaffolding so attendance has something
# realistic to run against)
# ---------------------------------------------------------------------------

@app.post("/api/classes", status_code=201)
def create_class(payload: ClassCreate):
    if db.get_class(payload.class_id) is not None:
        raise HTTPException(409, f"Class {payload.class_id} already exists")
    db.create_class(payload.class_id, payload.class_name, payload.lecturer_id, payload.start_time, payload.end_time)
    return dict(db.get_class(payload.class_id))


@app.post("/api/classes/enroll", status_code=201)
def enroll_student(payload: EnrollRequest):
    if db.get_class(payload.class_id) is None:
        raise HTTPException(404, "Class not found")
    if db.get_student(payload.student_id) is None:
        raise HTTPException(404, "Student not found")
    db.enroll_student(payload.class_id, payload.student_id)
    return {"success": True, "class_id": payload.class_id, "student_id": payload.student_id}


@app.get("/api/classes/{class_id}/students")
def enrolled_students(class_id: str):
    if db.get_class(class_id) is None:
        raise HTTPException(404, "Class not found")
    return [dict(r) for r in db.get_enrolled_students(class_id)]


# ---------------------------------------------------------------------------
# FR-2: Face Registration
# Mirrors pseudocode section 5.3 registerStudentFace(studentID, capturedImages[])
# ---------------------------------------------------------------------------

@app.post("/api/face/register")
def register_face(payload: FaceRegistrationRequest):
    student_id = payload.student_id
    captured_images = payload.images

    # 2. Verify the student exists and doesn't already have a registered face
    student = db.get_student(student_id)
    if student is None:
        return {"success": False, "message": "Student not found"}

    if student["face_registered"]:
        return {"success": False, "message": "Face already registered for this student"}

    # 3. Verify the minimum number of images received
    if len(captured_images) < fe.MIN_REGISTRATION_IMAGES:
        return {
            "success": False,
            "message": f"Minimum {fe.MIN_REGISTRATION_IMAGES} images required",
        }

    # 4. Process each captured image
    validated_images: List[np.ndarray] = []
    embeddings: List[np.ndarray] = []
    per_image_results = []

    for idx, image_data in enumerate(captured_images):
        image, embedding, reasons = fe.process_registration_image(image_data)
        per_image_results.append({"index": idx, "accepted": embedding is not None, "reasons": reasons})
        if embedding is not None and image is not None:
            validated_images.append(image)
            embeddings.append(embedding)

    # 5. Verify sufficient valid images were processed
    if len(validated_images) < fe.MIN_REGISTRATION_IMAGES:
        return {
            "success": False,
            "message": "Not enough valid face images. Please retake photos",
            "valid_image_count": len(validated_images),
            "required": fe.MIN_REGISTRATION_IMAGES,
            "details": per_image_results,
        }

    # 6. Calculate average embedding from all validated images
    average_embedding = fe.average_embeddings(embeddings)

    # 7. Encrypt the facial embedding before storage
    encrypted_embedding = cu.encrypt_embedding(average_embedding)

    # 8. Store valid images to (simulated) cloud storage
    storage_path = FACE_IMAGE_DIR / student_id
    storage_path.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(validated_images):
        out_path = storage_path / f"img_{i:02d}.jpg"
        cv2.imwrite(str(out_path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

    # 9. Store facial feature record to database
    db.save_facial_record(student_id, str(storage_path), len(validated_images), encrypted_embedding)

    # 10. Update student record
    db.set_face_registered(student_id)

    # 11. Return success response
    return {
        "success": True,
        "message": "Face registration completed successfully",
        "valid_image_count": len(validated_images),
        "rejected_image_count": len(captured_images) - len(validated_images),
        "details": per_image_results,
    }


@app.get("/api/face/status/{student_id}")
def face_status(student_id: str):
    student = db.get_student(student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    record = db.get_facial_record(student_id)
    return {
        "student_id": student_id,
        "face_registered": bool(student["face_registered"]),
        "photo_count": record["no_of_photos"] if record else 0,
        "registration_date": record["registration_date"] if record else None,
    }


# ---------------------------------------------------------------------------
# FR-6.1: Start an attendance session
# ---------------------------------------------------------------------------

@app.post("/api/attendance/sessions", status_code=201)
def start_attendance_session(payload: SessionStartRequest):
    cls = db.get_class(payload.class_id)
    if cls is None:
        return {"success": False, "message": "Class not found"}

    if payload.enforce_class_time:
        now = datetime.now()
        start = datetime.combine(now.date(), datetime.strptime(cls["start_time"], "%H:%M").time())
        end = datetime.combine(now.date(), datetime.strptime(cls["end_time"], "%H:%M").time())
        if not (start <= now <= end):
            return {
                "success": False,
                "message": f"Attendance can only be started during class time ({cls['start_time']}-{cls['end_time']})",
            }

    session_id = db.create_attendance_session(payload.class_id, payload.lecturer_id)
    enrolled = db.get_enrolled_students(payload.class_id)
    return {
        "success": True,
        "session_id": session_id,
        "class_id": payload.class_id,
        "enrolled_count": len(enrolled),
        "enrolled_students": [dict(r) for r in enrolled],
    }


@app.get("/api/attendance/sessions/{session_id}")
def get_session_status(session_id: str):
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    records = db.get_session_records(session_id)
    enrolled = db.get_enrolled_students(session["class_id"])
    present = sum(1 for r in records if r["attendance_status"] in ("Present", "Late"))
    return {
        "session": dict(session),
        "enrolled_count": len(enrolled),
        "recorded_count": len(records),
        "present_count": present,
        "records": [dict(r) for r in records],
    }


# ---------------------------------------------------------------------------
# FR-6.2: Automated face recognition attendance marking
# Mirrors pseudocode section 5.4 processAttendanceFrame(sessionId, classId, imageFrame)
# ---------------------------------------------------------------------------

@app.post("/api/attendance/frame")
def process_attendance_frame(payload: FrameRequest):
    started = time.perf_counter()

    # 2. Validate the attendance session is active
    session = db.get_session(payload.session_id)
    if session is None or session["status"] != "In Progress":
        return {"success": False, "message": "No active attendance session"}

    # 3. Decode the video frame
    try:
        frame = fe.decode_base64_image(payload.image_frame)
    except fe.FaceEngineError as exc:
        return {"success": False, "message": str(exc)}

    # 4. Detect all faces in the frame
    detected_faces = fe.detect_faces(frame)
    if len(detected_faces) == 0:
        return {
            "success": True,
            "facesDetected": 0,
            "recognizedStudents": [],
            "processingTimeMs": round((time.perf_counter() - started) * 1000, 1),
        }

    # 5 & 6. Get enrolled students and their (decrypted) facial embeddings
    facial_rows = db.get_facial_records_for_class(payload.class_id)
    student_embeddings = {}
    for row in facial_rows:
        try:
            decrypted = cu.decrypt_embedding(row["encrypted_embedding"])
        except ValueError:
            logger.warning("Could not decrypt facial data for student %s", row["student_id"])
            continue
        student_embeddings[row["student_id"]] = {
            "embedding": decrypted,
            "studentName": row["student_name"],
        }

    cls = db.get_class(payload.class_id)
    class_start = None
    if cls is not None:
        class_start = datetime.combine(datetime.now().date(), datetime.strptime(cls["start_time"], "%H:%M").time())

    recognized_students = []

    # 7. Process each detected face
    for face_location in detected_faces:
        try:
            current_embedding = fe.generate_embedding(frame, face_location)
        except fe.FaceEngineError:
            continue

        best_match = None
        highest_similarity = 0.0
        for student_id, student_data in student_embeddings.items():
            similarity = fe.cosine_similarity(current_embedding, student_data["embedding"])
            if similarity > highest_similarity:
                highest_similarity = similarity
                best_match = {
                    "studentId": student_id,
                    "studentName": student_data["studentName"],
                    "similarity": similarity,
                }

        if best_match is None or highest_similarity < fe.RECOGNITION_THRESHOLD:
            continue

        # 7.4 Skip if already marked for this session (no duplicate marking)
        existing = db.get_existing_attendance_record(payload.session_id, best_match["studentId"])
        if existing is not None:
            continue

        if class_start is not None and datetime.now() > class_start + timedelta(minutes=15):
            attendance_status = "Late"
        else:
            attendance_status = "Present"

        db.save_attendance_record(
            session_id=payload.session_id,
            student_id=best_match["studentId"],
            class_id=payload.class_id,
            status=attendance_status,
            method="Automated",
            marked_by=session["lecturer_id"],
            confidence=round(highest_similarity, 4),
        )

        top, right, bottom, left = face_location
        recognized_students.append(
            {
                "studentId": best_match["studentId"],
                "studentName": best_match["studentName"],
                "status": attendance_status,
                "confidence": round(highest_similarity, 4),
                "box": {"top": top, "right": right, "bottom": bottom, "left": left},
            }
        )

    return {
        "success": True,
        "facesDetected": len(detected_faces),
        "recognizedStudents": recognized_students,
        "timestamp": datetime.utcnow().isoformat(),
        "processingTimeMs": round((time.perf_counter() - started) * 1000, 1),
    }


# ---------------------------------------------------------------------------
# FR-6.3: Close attendance session
# ---------------------------------------------------------------------------

@app.post("/api/attendance/sessions/{session_id}/close")
def close_attendance_session(session_id: str, marked_by: str):
    session = db.get_session(session_id)
    if session is None:
        return {"success": False, "message": "Session not found"}
    if session["status"] != "In Progress":
        return {"success": False, "message": "Session is already closed"}

    newly_absent = db.mark_absentees(session_id, session["class_id"], marked_by)
    db.close_session(session_id)

    records = db.get_session_records(session_id)
    summary = {"Present": 0, "Late": 0, "Absent": 0}
    for r in records:
        summary[r["attendance_status"]] = summary.get(r["attendance_status"], 0) + 1

    return {
        "success": True,
        "session_id": session_id,
        "newly_marked_absent": newly_absent,
        "total_students": len(records),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# FR-6.4: Manual attendance marking by lecturer
# ---------------------------------------------------------------------------

@app.patch("/api/attendance/sessions/manual")
def manual_mark_attendance(payload: ManualAttendanceUpdate):
    if payload.status not in ("Present", "Absent", "Late"):
        raise HTTPException(422, "status must be one of Present, Absent, Late")

    session = db.get_session(payload.session_id)
    if session is None:
        return {"success": False, "message": "Session not found"}

    db.save_attendance_record(
        session_id=payload.session_id,
        student_id=payload.student_id,
        class_id=session["class_id"],
        status=payload.status,
        method="Manual",
        marked_by=payload.marked_by,
    )
    return {"success": True, "message": "Attendance updated"}


# ---------------------------------------------------------------------------
# FR-6.5: Student attendance view
# ---------------------------------------------------------------------------

@app.get("/api/attendance/students/{student_id}")
def student_attendance(student_id: str):
    if db.get_student(student_id) is None:
        raise HTTPException(404, "Student not found")
    records = db.get_attendance_for_student(student_id)
    total = len(records)
    present = sum(1 for r in records if r["attendance_status"] in ("Present", "Late"))
    percentage = round((present / total) * 100, 1) if total else 0.0
    return {
        "student_id": student_id,
        "total_sessions": total,
        "present_count": present,
        "attendance_percentage": percentage,
        "records": [dict(r) for r in records],
    }


# ---------------------------------------------------------------------------
# FR-6.6: Lecturer attendance report for a class
# ---------------------------------------------------------------------------

@app.get("/api/attendance/classes/{class_id}/report")
def class_attendance_report(class_id: str):
    cls = db.get_class(class_id)
    if cls is None:
        raise HTTPException(404, "Class not found")
    enrolled = db.get_enrolled_students(class_id)

    per_student = []
    for student in enrolled:
        records = [r for r in db.get_attendance_for_student(student["student_id"]) if r["class_id"] == class_id]
        total = len(records)
        present = sum(1 for r in records if r["attendance_status"] in ("Present", "Late"))
        per_student.append(
            {
                "student_id": student["student_id"],
                "name": student["name"],
                "sessions_recorded": total,
                "present_count": present,
                "attendance_percentage": round((present / total) * 100, 1) if total else 0.0,
            }
        )

    return {"class_id": class_id, "class_name": cls["class_name"], "students": per_student}
