# CogniFace Facial Recognition Service

This repository contains the private Python inference service used by the
CogniFace Node/Express API. It has no database access and must not be called by
the browser. Express supplies authorized face templates and remains responsible
for authentication, enrollment checks, and attendance writes.

## Responsibilities

- Validate registration photos and generate an averaged face embedding.
- Encrypt the embedding before returning it to Express for PostgreSQL storage.
- Detect and match faces in an attendance frame against the supplied class roster.
- Return proposed matches without creating or changing attendance records.

The service does not retain submitted images.

## Configuration

Use Python 3.11 or 3.12 and install `requirements.txt`. Required environment
variables:

```text
FACE_SERVICE_TOKEN=<shared secret also configured in Express>
FACE_ENCRYPTION_KEY=<Fernet key>
```

Optional settings:

```text
FACE_MATCH_MAX_DISTANCE=0.60
FACE_MATCH_AMBIGUITY_MARGIN=0.05
FACE_INFERENCE_CONCURRENCY=2
```

Generate a Fernet key once and keep it in secret storage:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Changing or losing this key makes existing embeddings unreadable.

## Run

```bash
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000
```

Only the Express server should be able to reach this port in a deployed
environment. Browser CORS is intentionally not enabled.

See `docs/API_ENDPOINTS.md` for the private contract.
