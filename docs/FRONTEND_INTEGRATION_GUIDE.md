# Frontend Integration Guide

How to point a separately-built frontend at this backend. For the full request/response contract, see [API_ENDPOINTS.md](API_ENDPOINTS.md).

## 1. Get the backend running

```bash
cd backend
# from a Python 3.11 or 3.12 venv with requirements.txt installed
uvicorn main:app --reload --port 8000
```

Confirm it's up:
```bash
curl http://127.0.0.1:8000/api/health
```

**Python version note**: `requirements.txt` pins `numpy<2.3`, which does not build from source on Python 3.14 (no prebuilt wheel yet, and its C headers predate 3.14's API changes). Use Python 3.11 or 3.12 for the venv. `dlib` also has no prebuilt Windows wheel and compiles from source — you need CMake and a C++ compiler (Visual Studio Build Tools) on the machine running the backend. See the main [README.md](../README.md) Setup section for the full pip install sequence, including the `face_recognition_models` and `setuptools<81` follow-up installs needed on a fresh venv (not in `requirements.txt` — `face_recognition`'s own packaging omits them).

The server serves on `http://127.0.0.1:8000` by default. Interactive docs at `/docs`.

## 2. Point your frontend at it

CORS is already open (`allow_origins=["*"]`) in [backend/main.py](../backend/main.py) — no proxy or CORS config needed on the frontend side, from any origin/port, in dev or prod as currently configured. (Worth tightening before a real deployment — see Known Quirks in the endpoint map.)

Give your frontend a single configurable API base URL (env var, config file, or a settings field) rather than hardcoding `localhost:8000` — you'll want to point it at a different host once this isn't running on your laptop. Nothing else about the wiring requires a build step or SDK; it's plain REST + JSON, callable with `fetch`/`axios`/whatever your stack already uses.

## 3. Core workflows to wire up

These map directly to the six functional requirements the backend implements. Build/verify in this order — each depends on data created by the previous one.

### a. Roster setup
`POST /api/students` → `POST /api/classes` → `POST /api/classes/enroll`. Needed before anything else works — a session with no enrolled students, or recognition against a class with no registered faces, will run but do nothing useful.

### b. Face registration
`POST /api/face/register` needs **≥15 accepted images** per student. This is a UI-heavy endpoint, not a simple form submit:
- Drive a `<video>` element from `getUserMedia`, capture frames to a `<canvas>`, export as base64 JPEG (`canvas.toDataURL('image/jpeg', 0.9)`).
- Capture more than 15 (18–20) since some will be rejected for blur/lighting/face-too-small — the response's `details[]` array tells you which and why, per image; surface those reasons to the user so they know what to fix on retake, rather than just failing silently.
- Check `GET /api/face/status/{student_id}` before showing the registration flow at all — there's no re-registration endpoint, so if `face_registered` is already `true`, don't offer to register again (the backend will just reject it).

### c. Attendance session lifecycle
`POST /api/attendance/sessions` (start) → repeated `POST /api/attendance/frame` (recognize) → `POST /api/attendance/sessions/{id}/close?marked_by=...` (close). This is the live/real-time part:
- Poll or stream frames from a webcam feed at a modest interval (the reference frontend in `frontend/` in this repo uses a 2s default, configurable) — there's no websocket/streaming endpoint, it's plain request/response per frame, so faster polling = more server load for diminishing returns given `hog`-model detection latency.
- `recognizedStudents` in each frame response is only *newly* recognized faces, not the full roster state — drive a running "just marked" list from it, and pull the authoritative full state from `GET /api/attendance/sessions/{id}` (poll this less frequently, e.g. on each recognition event or every 5-10s).
- Always closes with `newly_marked_absent` covering anyone never recognized — surface that count so the lecturer knows the session auto-completed the roster.

### d. Manual override
`PATCH /api/attendance/sessions/manual` — a simple form (student + status dropdown) for the lecturer to correct/backfill a status. Useful as a fallback when recognition misses someone or gets it wrong.

### e. Reporting
`GET /api/attendance/students/{id}` and `GET /api/attendance/classes/{id}/report` — read-only, safe to call freely, no side effects.

## 4. A reference implementation exists in this repo

[frontend/](../frontend/) contains a minimal working vanilla-JS client (no build step, no framework) that exercises every endpoint above, including the webcam capture flows. If your separately-built frontend is missing a piece of this wiring (especially the webcam-to-base64 capture, or the auto-recognition polling loop), it's a working reference to copy the pattern from rather than reverse-engineering it from the API docs alone — see [frontend/app.js](../frontend/app.js).

## 5. Testing the integration

1. Start the backend (`uvicorn main:app --reload --port 8000` from `backend/`).
2. Start your frontend pointed at that base URL.
3. `GET /api/health` should succeed from the frontend's origin (confirms CORS + connectivity) before testing anything else.
4. Walk the workflow in order (§3a → §3e) with real UI interactions, not just isolated API calls — the face registration and live-recognition flows in particular need a real camera to validate meaningfully; curling the endpoints with a canned base64 string only proves the wiring, not the UX.
5. Check `backend`'s console output (uvicorn logs) when something doesn't behave as expected — decode/detection errors, stack traces, and the `--reload` watcher's status all print there.

## 6. If you're handing this off to an agent

See [AGENT.md](../AGENT.md) at the repo root — it's written specifically for an agent tasked with wiring an existing frontend codebase to this backend, and points back to this guide and the endpoint map for the contract details.
