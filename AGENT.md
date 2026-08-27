# AGENT.md — Connecting the frontend to the facial-recognition backend

You are wiring an existing, separately-built frontend to the FastAPI backend in this repo (`backend/`). The backend is done and working — your job is integration, not building new backend features. Read this whole file before touching code.

## Orientation — read these first, in order

1. [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md) — the full request/response contract for every endpoint. This is your primary reference; don't guess at shapes, they're all documented there with real examples.
2. [docs/FRONTEND_INTEGRATION_GUIDE.md](docs/FRONTEND_INTEGRATION_GUIDE.md) — the workflows, in the order they need to be wired, plus setup/testing steps.
3. [frontend/](frontend/) — a minimal working reference client (vanilla JS, no build step) that already calls every endpoint, including the webcam-capture flows. If you're unsure how a flow should work end-to-end (especially face registration or live recognition), read [frontend/app.js](frontend/app.js) before inventing your own approach.
4. [backend/main.py](backend/main.py) — if the docs and the actual code ever disagree, the code is the ground truth. The docs were written from this file; if you find a mismatch, trust `main.py` and flag the doc as stale.

## Your task

Find the frontend codebase (the user will tell you where it lives if it's not in this repo — do not assume it's the `frontend/` folder here, that's the reference implementation, not the target). Then:

1. Identify its stack (React/Vue/Next/mobile/etc.), its existing API-calling conventions (fetch wrapper, axios instance, generated client, etc.), and where UI already exists for each workflow in §3 of the integration guide.
2. Add or fix the HTTP calls to match the documented contract exactly — paths, methods, body shapes, and the query-param exception (`close` session's `marked_by`).
3. Wire the success/failure handling correctly. **This is the most common integration bug**: several endpoints return HTTP 200 with `{"success": false, "message": "..."}` instead of a 4xx. If the frontend only checks `response.ok`, these failures will silently look like successes. Check the endpoint map's "Error format summary" table and handle both cases.
4. Add a single configurable API base URL (env var or config, not hardcoded) if the frontend doesn't already have one.
5. Wire the webcam-based flows (face registration, live recognition) if they don't already exist — copy the capture pattern from `frontend/app.js` (`getUserMedia` → `<canvas>` → `toDataURL('image/jpeg', ...)` → base64 into the request body). Don't reinvent the image encoding; the backend expects exactly this format (raw base64 or a `data:` URL, JPEG/PNG).
6. Confirm CORS isn't an issue — it's already wide open server-side (`allow_origins=["*"]` in `main.py`), so a CORS error means the request isn't reaching the backend at all (wrong port/path/protocol), not a server-side config problem to fix.

## Environment setup

The backend needs a running Python process to test against:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

**If dependencies aren't installed yet**: use a Python 3.11 or 3.12 venv, not 3.14+ — `numpy<2.3` (pinned in `requirements.txt`) fails to build from source on 3.14 (no prebuilt wheel exists yet, and its headers predate 3.14's C API changes). After `pip install -r requirements.txt`, you'll likely also need:
```bash
pip install git+https://github.com/ageitgey/face_recognition_models
pip install "setuptools<81"
```
(`face_recognition`'s PyPI packaging omits its own model-weights dependency, and newer `setuptools` dropped `pkg_resources`, which that package still imports.) `dlib` compiles from source on Windows and needs CMake + a C++ compiler (Visual Studio Build Tools) present on the machine.

Verify before wiring anything: `curl http://127.0.0.1:8000/api/health` should return `{"status": "ok", ...}`.

## Validation checklist before you consider this done

Walk these against the **real running backend**, not mocks — the point of this task is a working integration, and several failure modes (the 200-with-`success:false` pattern, the `marked_by` query param, base64 image format) only show up against the real server.

- [ ] `GET /api/health` succeeds from the frontend's origin (proves connectivity + CORS)
- [ ] Create a student, a class, and an enrollment through the frontend UI
- [ ] Register a face for that student with a real camera — verify it handles rejected images (blurry/dark/no-face) by surfacing the per-image reason, not just failing generically
- [ ] Start an attendance session, verify enrolled count shows correctly
- [ ] Feed live camera frames and confirm recognized students appear (needs a face actually registered above, in view of the camera)
- [ ] Manually mark a student's status and confirm it reflects immediately
- [ ] Close the session and confirm unrecognized students show as `Absent`
- [ ] Pull both report views (student + class) and confirm the numbers match what you just did
- [ ] Deliberately trigger at least one `success:false` case (e.g. try registering a face for a student that already has one) and confirm the frontend shows an error, not a false "success" state

## Don't

- Don't add authentication, pagination, or new backend endpoints to solve a frontend problem — flag it to the user instead. The backend's scope is intentionally fixed (see README's "known limitations"); if the frontend needs something the API doesn't provide (e.g. delete/re-register a face), that's a product decision, not something to route around unilaterally.
- Don't change `RECOGNITION_THRESHOLD`, image quality thresholds, or other tuned constants in `backend/face_engine.py` to make frontend testing more convenient — they're calibration values, not arbitrary. If recognition seems too strict/loose during testing, flag it rather than silently tuning it.
- Don't hardcode the API base URL if the frontend has an existing config/env pattern — use that instead of introducing a new one.
- Don't assume the reference `frontend/` in this repo is what you're replacing/editing — confirm with the user which codebase is the actual integration target before making changes.
