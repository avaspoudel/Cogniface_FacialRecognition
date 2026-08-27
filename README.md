# Facial Recognition Attendance API

A working FastAPI service implementing the facial-recognition part of the
**Cloud-Based Attendance System Using Facial Recognition** capstone
proposal: FR‑2 (Face Registration) and FR‑6 (Attendance Management),
built to follow the pseudocode in sections 5.3 and 5.4 of the report as
closely as practical.

This is a **local, from-scratch prototype** of the facial recognition
engine and its API — SQLite stands in for the eventual cloud database,
and the local filesystem stands in for cloud object storage. The
recognition logic, data model, and API contracts are the real thing; the
infrastructure they'd run on in production (RDS/Cloud SQL, S3/Blob
Storage, KMS, auto-scaling, etc.) is out of scope for this piece.

## What's in here

```
backend/
  main.py           FastAPI app - all HTTP endpoints
  face_engine.py     Face detection, quality scoring, embeddings, similarity
  database.py         SQLite schema + queries (Students, FacialFeatures,
                       Classes, Enrollments, AttendanceSessions, AttendanceRecords)
  crypto_utils.py     Encrypts/decrypts embeddings at rest (Fernet)
  schemas.py           Pydantic request models
  calibrate.py          Standalone script to help you pick a real
                         recognition threshold from your own photos
  tests/test_api.py    Integration tests (7 tests, all passing)
  storage/             SQLite DB file, encryption key, and registered
                        face images live here at runtime (gitignored)
requirements.txt
```

## Setup

```bash
cd facial-attendance
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# dlib needs a C++ compiler + cmake. On Ubuntu/Debian:
#   sudo apt install build-essential cmake
# On macOS:
#   brew install cmake
pip install -r requirements.txt
```

> **Why a venv, and why an older setuptools pin might matter:** `dlib`
> and `face_recognition_models` still ship old-style `setup.py` builds.
> If `pip install face_recognition` fails with an
> `AttributeError: install_layout` error, run
> `pip install "setuptools<66"` first, then retry. That's a known
> incompatibility between very new setuptools and these packages, not a
> problem with your machine.

Run the API:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open **http://127.0.0.1:8000/docs** for interactive Swagger UI — this is
the fastest way to try every endpoint by hand (registration needs actual
photos, but you can create students/classes and exercise everything else
straight from the browser).

Run the tests:

```bash
cd backend
pytest -q
```

## How the pieces map to the proposal

| Proposal section | Where it lives |
|---|---|
| FR‑2: Face Registration | `POST /api/face/register` in `main.py`, following the `registerStudentFace()` algorithm in section 5.3 step-by-step (numbered comments in the code match the numbered steps in the pseudocode) |
| FR‑6.1: Start attendance session | `POST /api/attendance/sessions` |
| FR‑6.2: Automated recognition | `POST /api/attendance/frame`, following `processAttendanceFrame()` in section 5.4 |
| FR‑6.3: Close session | `POST /api/attendance/sessions/{id}/close` (marks unrecorded enrolled students absent) |
| FR‑6.4: Manual marking | `PATCH /api/attendance/sessions/manual` |
| FR‑6.5: Student attendance view | `GET /api/attendance/students/{id}` |
| FR‑6.6: Lecturer report | `GET /api/attendance/classes/{id}/report` |
| FR‑2.1.14 / NFR‑14: Encryption | `crypto_utils.py` — embeddings are Fernet-encrypted before they ever touch the database |
| NFR‑3: Face Recognition performance | `main.py`'s frame endpoint returns `processingTimeMs` on every call so you can measure against the <400ms/<1s/<2s targets on your own hardware |

## API walkthrough

```bash
# 1. Create a student and a class, then enroll
curl -X POST localhost:8000/api/students -H "Content-Type: application/json" \
  -d '{"student_id":"S001","name":"Aavash Poudel"}'

curl -X POST localhost:8000/api/classes -H "Content-Type: application/json" \
  -d '{"class_id":"C001","class_name":"Databases","lecturer_id":"L001","start_time":"09:00","end_time":"10:00"}'

curl -X POST localhost:8000/api/classes/enroll -H "Content-Type: application/json" \
  -d '{"class_id":"C001","student_id":"S001"}'

# 2. Register a face - `images` needs >=15 base64 JPEG/PNG strings.
#    (This is exactly what a browser webcam capture flow would send.)
curl -X POST localhost:8000/api/face/register -H "Content-Type: application/json" \
  -d '{"student_id":"S001","images":["<base64>", "... 15+ total ..."]}'

# 3. Start a session, then feed it frames as they come off a camera
curl -X POST localhost:8000/api/attendance/sessions -H "Content-Type: application/json" \
  -d '{"class_id":"C001","lecturer_id":"L001"}'
#  -> {"session_id": "...", ...}

curl -X POST localhost:8000/api/attendance/frame -H "Content-Type: application/json" \
  -d '{"session_id":"<id>","class_id":"C001","image_frame":"<base64>"}'

# 4. Close it out
curl -X POST "localhost:8000/api/attendance/sessions/<id>/close?marked_by=L001"
```

## Design notes & known limitations (worth citing in your report)

- **Library choice**: `face_recognition` (dlib's ResNet-based model, 128‑d
  embeddings). Fast enough on CPU for a capstone-scale deployment and
  well documented, at the cost of being a bit less accurate than newer
  models like ArcFace under difficult lighting/angles.
- **Cosine similarity vs. the model's native metric**: the pseudocode
  specifies cosine similarity with a 0.85 threshold. dlib's embeddings
  were actually trained against *Euclidean* distance (rule of thumb:
  <0.6 = same person). Both metrics are implemented in `face_engine.py`;
  use `calibrate.py` with a handful of your own photos to pick and
  justify a real threshold rather than trusting 0.85 blindly — this is
  good evidence for your NFR‑3 write-up.
- **Image quality scoring** (`assess_image_quality`) is a heuristic:
  blur via Laplacian variance, brightness via mean pixel intensity, and
  face size relative to frame. It's deliberately simple and documented
  in the code so it's easy to explain in a viva; a production system
  might add pose/occlusion checks.
- **Guided head-turn capture** (FR‑2.1.4) is left to the frontend to
  implement as a UI sequence (prompt "look left" / "look right" / etc.
  and auto-capture on a timer) — this backend just validates whatever
  images arrive. True head-pose estimation (via dlib's 68 landmarks) is
  a reasonable stretch goal if you want to actually enforce angle
  coverage rather than trust the UI prompts.
- **Encryption key management**: `crypto_utils.py` generates and stores
  a Fernet key on the local filesystem (`storage/encryption.key`) for
  convenience. In a real cloud deployment this key belongs in a managed
  secret store (AWS Secrets Manager / KMS, Azure Key Vault) — the code
  comment marks exactly where that swap would happen.
- **SQLite instead of a cloud DB**: schema and queries in `database.py`
  are written in plain SQL specifically so the swap to Postgres/RDS
  later is mechanical (same schema, different connection string) rather
  than a rewrite.
- **Testing approach**: `tests/test_api.py` monkeypatches the ML calls
  (`detect_faces`, `generate_embedding`) with deterministic stand-ins,
  because this sandboxed dev environment has no real face photos to test
  against. This validates all the *business logic* — registration
  rules, duplicate-prevention, session lifecycle, Present/Late timing —
  independent of model accuracy. `face_engine.py`'s non-ML functions
  (decode, quality scoring, similarity math) are exercised directly
  against real dlib/OpenCV calls. **You should still test the real
  detection/embedding pipeline against your own photos** before relying
  on it for a demo — that's exactly what `calibrate.py` and the
  `/api/face/register` endpoint (called from a real browser) are for.

## Suggested next steps

1. Capture some real test photos (yourself, teammates) and run
   `calibrate.py` to pick a defensible recognition threshold.
2. Build the browser webcam client (capture → register, live frame
   feed → recognize) — happy to build this next if you want it.
3. Swap SQLite for your team's actual cloud database once the rest of
   the system (auth, enrollment) is ready to integrate against it.
4. Add JWT-based role checks (NFR‑12/13) once the auth module exists —
   right now these endpoints are open, matching the scope of "just the
   facial recognition part."
