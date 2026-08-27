# API Endpoint Map — Facial Recognition Attendance API

Base URL (local dev): `http://127.0.0.1:8000`
Interactive docs: `http://127.0.0.1:8000/docs` (Swagger) — always the source of truth if this file drifts.

All request/response bodies are JSON unless noted. CORS is wide open (`allow_origins=["*"]`) so any frontend origin/port can call this API directly — no proxy needed.

Server implementation: [backend/main.py](../backend/main.py). Request schemas: [backend/schemas.py](../backend/schemas.py). DB row shapes: [backend/database.py](../backend/database.py).

---

## Conventions

- **IDs are caller-supplied strings**, not auto-generated (except `session_id` and `attendance_id`, which are server-generated UUIDs). `student_id` and `class_id` are whatever the frontend chooses (e.g. `"S001"`, `"C001"`) — the frontend owns uniqueness at input time; the API 409s on duplicates.
- **Success/failure shape is inconsistent by design** — some endpoints use HTTP status codes + `HTTPException` (404/409/422), others return `200` with a body `{"success": false, "message": "..."}`. See the per-endpoint notes below; **check `success` in the body even on a 200**, don't assume 200 means the operation happened.
- **Images** are base64 strings, either raw base64 or a full `data:image/jpeg;base64,....` data URL (the API strips the prefix if present). JPEG or PNG. Captured from a `<canvas>.toDataURL('image/jpeg', 0.9)` is the expected source.
- **Times** (`start_time`/`end_time` on classes) are `"HH:MM"` 24-hour strings, no seconds, no timezone.
- **Timestamps** returned by the API are ISO 8601 UTC strings (`datetime.utcnow().isoformat()` / `datetime.now().isoformat()` — note: mixed UTC/local, see Known Quirks below).

---

## Health

### `GET /api/health`
No auth, no params. Use this to drive a connectivity indicator in the frontend.

**Response 200**
```json
{ "status": "ok", "time": "2026-08-27T10:00:00.000000" }
```

---

## Students

### `POST /api/students`
Create a student.

**Body**
```json
{ "student_id": "S001", "name": "Aavash Poudel", "email": "optional@example.com" }
```
`email` is optional.

**Response 201** — the created row:
```json
{ "student_id": "S001", "name": "Aavash Poudel", "email": null, "face_registered": 0, "created_at": "..." }
```
**Response 409** — `{"detail": "Student S001 already exists"}` if `student_id` is taken.

### `GET /api/students`
List all students. **Response 200**: array of the row shape above.

### `GET /api/students/{student_id}`
**Response 200**: single row. **Response 404** if not found.

---

## Classes & Enrollment

### `POST /api/classes`
**Body**
```json
{ "class_id": "C001", "class_name": "Databases", "lecturer_id": "L001", "start_time": "09:00", "end_time": "10:00" }
```
**Response 201**: created row. **Response 409** if `class_id` exists.

### `POST /api/classes/enroll`
**Body**: `{ "class_id": "C001", "student_id": "S001" }`
**Response 201**: `{ "success": true, "class_id": "...", "student_id": "..." }`
**Response 404**: `{"detail": "Class not found"}` or `{"detail": "Student not found"}`.
Idempotent — re-enrolling the same pair is `INSERT OR REPLACE`, not an error.

### `GET /api/classes/{class_id}/students`
Enrolled students for a class. **Response 200**: `[{ "student_id": "...", "name": "..." }, ...]`. **404** if class doesn't exist.

---

## Face Registration (FR-2)

### `POST /api/face/register`
**Body**
```json
{ "student_id": "S001", "images": ["<base64 or data: URL>", "... at least 15 total ..."] }
```

**This is the endpoint most likely to need frontend UX work.** Behavior:
- Requires **≥ 15 images** in the request, and **≥ 15 must individually pass validation** (face detected, exactly one face, quality score ≥ 50/100) after processing — sending exactly 15 with some rejected will fail with a "not enough valid images" message, so the frontend should either over-capture (e.g. 18–20 shots) or loop until 15 are accepted.
- Rejects if the student already has a face registered (one registration per student; no re-registration endpoint exists yet).
- Always returns **HTTP 200** — check `success` in the body, not the status code.

**Response 200, success**
```json
{
  "success": true,
  "message": "Face registration completed successfully",
  "valid_image_count": 17,
  "rejected_image_count": 2,
  "details": [
    { "index": 0, "accepted": true, "reasons": [] },
    { "index": 1, "accepted": false, "reasons": ["Image is too dark"] }
  ]
}
```
`details[].reasons` values to expect and can surface to the user: `"No face detected"`, `"Multiple faces detected"`, `"Image appears blurry"`, `"Image is too dark"`, `"Image is too bright / overexposed"`, `"Face is too small / too far from camera"`, or a decode error string.

**Response 200, failure** (one of):
```json
{ "success": false, "message": "Student not found" }
{ "success": false, "message": "Face already registered for this student" }
{ "success": false, "message": "Minimum 15 images required" }
{ "success": false, "message": "Not enough valid face images. Please retake photos", "valid_image_count": 9, "required": 15, "details": [...] }
```

### `GET /api/face/status/{student_id}`
**Response 200**
```json
{ "student_id": "S001", "face_registered": true, "photo_count": 17, "registration_date": "2026-08-27T..." }
```
**404** if student doesn't exist. Use this to gate the UI (e.g. disable "start session" or show a "register face" prompt).

---

## Attendance Sessions (FR-6.1 / FR-6.3)

### `POST /api/attendance/sessions`
Starts a session for a class. A lecturer/camera view should call this once at the start of class.

**Body**
```json
{ "class_id": "C001", "lecturer_id": "L001", "enforce_class_time": false }
```
`enforce_class_time` (default `false`): if `true`, the server rejects starting the session outside the class's `start_time`–`end_time` window (server local time, today's date).

**Response 200, success**
```json
{
  "success": true,
  "session_id": "5286e2bd-9270-4a00-89e0-99044652a781",
  "class_id": "C001",
  "enrolled_count": 1,
  "enrolled_students": [{ "student_id": "S001", "name": "Aavash Poudel" }]
}
```
**Response 200, failure**: `{"success": false, "message": "Class not found"}` or the class-time-window message.

Again: **always 200**, check `success`.

### `GET /api/attendance/sessions/{session_id}`
Poll this for a live dashboard. **Response 200**
```json
{
  "session": { "session_id": "...", "class_id": "...", "lecturer_id": "...", "status": "In Progress", "start_time": "...", "end_time": null },
  "enrolled_count": 1,
  "recorded_count": 1,
  "present_count": 0,
  "records": [ { "attendance_id": "...", "session_id": "...", "student_id": "S001", "class_id": "C001",
                 "attendance_datetime": "...", "attendance_status": "Absent", "recognition_method": "Automated",
                 "confidence": null, "marked_by": "L001", "created_at": "...", "student_name": "Aavash Poudel" } ]
}
```
**404** if session doesn't exist.

### `POST /api/attendance/sessions/{session_id}/close?marked_by=L001`
`marked_by` is a **required query parameter**, not a body field. Marks any enrolled student with no record yet as `Absent`, then closes the session.

**Response 200, success**
```json
{ "success": true, "session_id": "...", "newly_marked_absent": 1, "total_students": 1, "summary": { "Present": 0, "Late": 0, "Absent": 1 } }
```
**Response 200, failure**: `{"success": false, "message": "Session not found"}` or `"Session is already closed"`.

---

## Live Recognition (FR-6.2)

### `POST /api/attendance/frame`
The hot path — call this repeatedly (e.g. every 1–3s) with frames from a webcam while a session is `"In Progress"`.

**Body**
```json
{ "session_id": "...", "class_id": "...", "image_frame": "<base64 or data: URL>" }
```

**Response 200**
```json
{
  "success": true,
  "facesDetected": 2,
  "recognizedStudents": [
    { "studentId": "S001", "studentName": "Aavash Poudel", "status": "Present", "confidence": 0.912,
      "box": { "top": 40, "right": 220, "bottom": 200, "left": 60 } }
  ],
  "timestamp": "2026-08-27T...",
  "processingTimeMs": 187.3
}
```
Notes:
- `recognizedStudents` only includes **newly-matched** faces above `RECOGNITION_THRESHOLD` (0.85 cosine similarity) that haven't already been recorded for this session — a student recognized twice in two frames only appears in the response of the first frame that caught them. Don't expect it to re-announce someone every frame; use it to append to a "just marked" list, not as the full roster state (poll `GET /api/attendance/sessions/{id}` for that).
- `box` coordinates are in the pixel space of the frame you sent — useful for drawing a bounding box overlay on the `<video>`/`<canvas>` if desired, but the frontend must scale them if it displays the video at a different resolution than it captured.
- `status` is `"Present"` or `"Late"` (Late = more than 15 minutes after the class's `start_time`, server local time).
- If no active session: `{"success": false, "message": "No active attendance session"}` (200).
- If image can't be decoded: `{"success": false, "message": "<decode error>"}` (200).
- No error is returned for zero faces — `facesDetected: 0, recognizedStudents: []` is a normal response, expect it constantly (empty frames, no one in view).

---

## Manual Marking (FR-6.4)

### `PATCH /api/attendance/sessions/manual`
Note the path — **not** `/{session_id}/manual`, session ID is in the body.

**Body**
```json
{ "session_id": "...", "student_id": "S001", "status": "Present", "marked_by": "L001" }
```
`status` must be exactly one of `"Present"`, `"Absent"`, `"Late"` (case-sensitive). **422** if not.

**Response 200**: `{"success": true, "message": "Attendance updated"}` or `{"success": false, "message": "Session not found"}`.
Upserts — calling twice for the same student/session overwrites the previous status (see `ON CONFLICT` in `database.py`).

---

## Reports (FR-6.5 / FR-6.6)

### `GET /api/attendance/students/{student_id}`
**Response 200**
```json
{
  "student_id": "S001", "total_sessions": 4, "present_count": 3, "attendance_percentage": 75.0,
  "records": [ { "...same shape as session records, plus": "class_name" } ]
}
```
`records` spans **all classes**, newest first. **404** if student doesn't exist.

### `GET /api/attendance/classes/{class_id}/report`
**Response 200**
```json
{
  "class_id": "C001", "class_name": "Databases",
  "students": [ { "student_id": "S001", "name": "...", "sessions_recorded": 4, "present_count": 3, "attendance_percentage": 75.0 } ]
}
```
**404** if class doesn't exist.

---

## Error format summary

| Situation | HTTP status | Body |
|---|---|---|
| Resource not found (student/class/session lookup by path param) | 404 | `{"detail": "..."}` (FastAPI default) |
| Duplicate create (student/class) | 409 | `{"detail": "..."}` |
| Bad `status` value in manual marking | 422 | `{"detail": "..."}` |
| Pydantic validation failure (missing/wrong-typed field) | 422 | FastAPI's standard validation error body |
| Business-logic failure the API expects as a normal outcome (class not found on session start, no active session, already registered, etc.) | **200** | `{"success": false, "message": "..."}` |

**Frontend implication**: your HTTP client needs to check `response.ok` (for 404/409/422) *and* `body.success === false` (for the 200-with-failure cases) — a single `catch` on non-2xx will miss the second category entirely.

---

## Known quirks worth knowing before wiring the frontend

1. **No auth.** Every endpoint is open. If your frontend has a login flow, it's not enforced by this API yet (see README's "Suggested next steps").
2. **Timestamps mix UTC and local time.** `/api/health` and frame-processing timestamps use `datetime.utcnow()`; class-time-window and Late/Present cutoff logic uses `datetime.now()` (server local time). If the frontend does its own "is it Late" calculation for display, use local time to match the server, not the UTC timestamps.
3. **One face registration per student, ever.** There's no "re-register" or "delete registration" endpoint. If you need that in the frontend, it doesn't exist yet on the backend — flag it rather than building UI for it.
4. **`POST /api/attendance/sessions/{id}/close` takes `marked_by` as a query param**, easy to miss if you're used to everything being a body field.
5. **No pagination anywhere.** `GET /api/students`, class rosters, and attendance history all return full result sets. Fine at capstone scale; will need pagination params added if that changes.
6. **`main.py` auto-reloads** (`uvicorn --reload`) during dev — backend changes take effect without a manual restart, but a bad edit will crash the reloader; check `uvicorn` console output if the frontend suddenly gets connection-refused.
