"""
Integration tests for the FastAPI attendance service.

Real face detection/embedding (dlib) needs an actual photographed face,
which this sandboxed test environment doesn't have. So these tests
monkeypatch `face_engine`'s detection/embedding functions with
deterministic stand-ins and focus on verifying the *business logic*
that sits around the ML calls: the FR-2 registration rules, the FR-6.2
recognition/duplicate-prevention flow, session lifecycle, and the
report endpoints. `face_engine.py` itself already has separate
non-ML-dependent smoke coverage (decode, quality scoring, cosine
similarity, averaging) run directly against real dlib/OpenCV calls.

Run with:
    pytest -q
"""

import base64
import importlib
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

FAKE_JPEG_B64 = base64.b64encode(b"not a real jpeg but non-empty").decode()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh app + isolated DB/encryption-key/storage per test."""
    import database as db
    import crypto_utils as cu
    import main as app_module

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "attendance.db")
    monkeypatch.setattr(cu, "KEY_PATH", tmp_path / "encryption.key")
    monkeypatch.setattr(cu, "_fernet", cu.Fernet(cu._load_or_create_key()))
    monkeypatch.setattr(app_module, "FACE_IMAGE_DIR", tmp_path / "face_images")

    from fastapi.testclient import TestClient

    db.init_db()
    (tmp_path / "face_images").mkdir(parents=True, exist_ok=True)
    return TestClient(app_module.app)


def _mock_face_pipeline(monkeypatch, embedding_by_call):
    """
    Patch face_engine so that:
      - decode_base64_image just returns a dummy array (skips real decode)
      - detect_faces returns one fixed bounding box
      - generate_embedding returns embeddings from `embedding_by_call`,
        one per call, in order (registration calls it once per image;
        frame processing calls it once per detected face)
    """
    import face_engine as fe
    import main as app_module

    calls = {"i": 0}

    def fake_decode(data):
        return np.zeros((100, 100, 3), dtype=np.uint8)

    def fake_detect(image, model=fe.FACE_DETECTION_MODEL):
        return [(0, 100, 100, 0)]

    def fake_quality(image, location):
        return fe.QualityReport(score=90.0, blur_score=90, brightness_score=90, size_score=90)

    def fake_embed(image, location):
        emb = embedding_by_call[calls["i"] % len(embedding_by_call)]
        calls["i"] += 1
        return emb

    monkeypatch.setattr(fe, "decode_base64_image", fake_decode)
    monkeypatch.setattr(fe, "detect_faces", fake_detect)
    monkeypatch.setattr(fe, "assess_image_quality", fake_quality)
    monkeypatch.setattr(fe, "generate_embedding", fake_embed)
    monkeypatch.setattr(app_module.fe, "decode_base64_image", fake_decode)
    monkeypatch.setattr(app_module.fe, "detect_faces", fake_detect)
    monkeypatch.setattr(app_module.fe, "generate_embedding", fake_embed)

    # process_registration_image calls the (now patched) module-level
    # functions internally, so patch it directly to use the same fakes.
    def fake_process_registration_image(raw_b64):
        image = fake_decode(raw_b64)
        faces = fake_detect(image)
        if len(faces) != 1:
            return image, None, ["face count problem"]
        q = fake_quality(image, faces[0])
        if not q.passed:
            return image, None, q.reasons
        return image, fake_embed(image, faces[0]), []

    monkeypatch.setattr(app_module.fe, "process_registration_image", fake_process_registration_image)


STUDENT_EMBEDDING = np.ones(128) * 0.9  # "Aavash"'s consistent face
OTHER_STUDENT_EMBEDDING = np.ones(128) * -0.9  # a clearly different face


def _setup_student_and_class(client, start_time=None):
    # Default the class to have started "now" so a frame processed
    # immediately after falls inside the on-time (Present) window; tests
    # that specifically want to exercise the "Late" path pass an
    # explicit, clearly-in-the-past start_time.
    start_time = start_time or datetime.now().strftime("%H:%M")
    client.post("/api/students", json={"student_id": "S001", "name": "Aavash Poudel"})
    client.post(
        "/api/classes",
        json={"class_id": "C001", "class_name": "Databases", "lecturer_id": "L001", "start_time": start_time, "end_time": "23:59"},
    )
    client.post("/api/classes/enroll", json={"class_id": "C001", "student_id": "S001"})


# ---------------------------------------------------------------------------
# FR-2: Face registration
# ---------------------------------------------------------------------------

def test_registration_rejects_too_few_images(client):
    _setup_student_and_class(client)
    resp = client.post("/api/face/register", json={"student_id": "S001", "images": [FAKE_JPEG_B64] * 5})
    body = resp.json()
    assert body["success"] is False
    assert "Minimum" in body["message"]


def test_registration_rejects_unknown_student(client, monkeypatch):
    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])
    resp = client.post("/api/face/register", json={"student_id": "GHOST", "images": [FAKE_JPEG_B64] * 15})
    body = resp.json()
    assert body["success"] is False
    assert body["message"] == "Student not found"


def test_registration_success_and_duplicate_rejected(client, monkeypatch):
    _setup_student_and_class(client)
    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])

    resp = client.post("/api/face/register", json={"student_id": "S001", "images": [FAKE_JPEG_B64] * 15})
    body = resp.json()
    assert body["success"] is True
    assert body["valid_image_count"] == 15

    status = client.get("/api/face/status/S001").json()
    assert status["face_registered"] is True
    assert status["photo_count"] == 15

    # second attempt should be rejected (FR-2: no double registration)
    resp2 = client.post("/api/face/register", json={"student_id": "S001", "images": [FAKE_JPEG_B64] * 15})
    assert resp2.json()["success"] is False
    assert "already registered" in resp2.json()["message"]


# ---------------------------------------------------------------------------
# FR-6.1 / 6.2: Attendance session + automated recognition
# ---------------------------------------------------------------------------

def test_full_attendance_flow(client, monkeypatch):
    _setup_student_and_class(client)
    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])
    client.post("/api/face/register", json={"student_id": "S001", "images": [FAKE_JPEG_B64] * 15})

    session_resp = client.post("/api/attendance/sessions", json={"class_id": "C001", "lecturer_id": "L001"})
    session = session_resp.json()
    assert session["success"] is True
    session_id = session["session_id"]

    # Frame recognition: the "current" face embedding matches the
    # enrolled student's stored embedding (same constant vector).
    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])
    frame_resp = client.post(
        "/api/attendance/frame",
        json={"session_id": session_id, "class_id": "C001", "image_frame": FAKE_JPEG_B64},
    )
    frame_body = frame_resp.json()
    assert frame_body["success"] is True
    assert frame_body["facesDetected"] == 1
    assert len(frame_body["recognizedStudents"]) == 1
    assert frame_body["recognizedStudents"][0]["studentId"] == "S001"
    assert frame_body["recognizedStudents"][0]["status"] == "Present"

    # Duplicate frame for the same session must NOT create a second record
    frame_resp_2 = client.post(
        "/api/attendance/frame",
        json={"session_id": session_id, "class_id": "C001", "image_frame": FAKE_JPEG_B64},
    )
    assert frame_resp_2.json()["recognizedStudents"] == []

    status = client.get(f"/api/attendance/sessions/{session_id}").json()
    assert status["recorded_count"] == 1
    assert status["present_count"] == 1

    # Close the session -> only one enrolled student, already present, so 0 newly absent
    close_resp = client.post(f"/api/attendance/sessions/{session_id}/close", params={"marked_by": "L001"})
    close_body = close_resp.json()
    assert close_body["success"] is True
    assert close_body["newly_marked_absent"] == 0
    assert close_body["summary"]["Present"] == 1

    # Session is now closed -> further frames should be rejected
    frame_after_close = client.post(
        "/api/attendance/frame",
        json={"session_id": session_id, "class_id": "C001", "image_frame": FAKE_JPEG_B64},
    ).json()
    assert frame_after_close["success"] is False


def test_late_status_after_grace_period(client, monkeypatch):
    # Class "started" well over 15 minutes ago -> recognized student should be marked Late.
    _setup_student_and_class(client, start_time="00:00")
    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])
    client.post("/api/face/register", json={"student_id": "S001", "images": [FAKE_JPEG_B64] * 15})

    session_id = client.post("/api/attendance/sessions", json={"class_id": "C001", "lecturer_id": "L001"}).json()["session_id"]

    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])
    frame_body = client.post(
        "/api/attendance/frame",
        json={"session_id": session_id, "class_id": "C001", "image_frame": FAKE_JPEG_B64},
    ).json()
    assert frame_body["recognizedStudents"][0]["status"] == "Late"


def test_unrecognized_face_is_not_marked(client, monkeypatch):
    _setup_student_and_class(client)
    _mock_face_pipeline(monkeypatch, [STUDENT_EMBEDDING])
    client.post("/api/face/register", json={"student_id": "S001", "images": [FAKE_JPEG_B64] * 15})

    session_id = client.post("/api/attendance/sessions", json={"class_id": "C001", "lecturer_id": "L001"}).json()["session_id"]

    # This frame's face embedding does NOT match the enrolled student
    _mock_face_pipeline(monkeypatch, [OTHER_STUDENT_EMBEDDING])
    frame_body = client.post(
        "/api/attendance/frame",
        json={"session_id": session_id, "class_id": "C001", "image_frame": FAKE_JPEG_B64},
    ).json()
    assert frame_body["recognizedStudents"] == []

    close_body = client.post(f"/api/attendance/sessions/{session_id}/close", params={"marked_by": "L001"}).json()
    assert close_body["newly_marked_absent"] == 1
    assert close_body["summary"]["Absent"] == 1


def test_manual_override_and_reports(client, monkeypatch):
    _setup_student_and_class(client)
    session_id = client.post("/api/attendance/sessions", json={"class_id": "C001", "lecturer_id": "L001"}).json()["session_id"]

    resp = client.patch(
        "/api/attendance/sessions/manual",
        json={"session_id": session_id, "student_id": "S001", "status": "Late", "marked_by": "L001"},
    )
    assert resp.json()["success"] is True

    history = client.get("/api/attendance/students/S001").json()
    assert history["total_sessions"] == 1
    assert history["present_count"] == 1  # "Late" counts toward present

    report = client.get("/api/attendance/classes/C001/report").json()
    assert report["students"][0]["student_id"] == "S001"
    assert report["students"][0]["attendance_percentage"] == 100.0
