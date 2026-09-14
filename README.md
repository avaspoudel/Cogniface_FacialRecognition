# CogniFace Facial Recognition Service

Private FastAPI service for registering facial templates and recognizing students from an authorized roster. The service is database-free and encrypts all generated face embeddings.

## Setup

Python 3.10+ is recommended. Create a virtual environment and install the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure the required secrets:

```bash
export FACE_SERVICE_TOKEN="your-internal-service-token"
export FACE_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

Keep the same encryption key between restarts; changing it makes existing facial templates unreadable.

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

All protected requests must include the `X-Internal-Service-Token` header. Only JPEG images up to 1 MB are accepted.

## Endpoints

- `GET /internal/health` — reports configuration readiness.
- `POST /internal/face/register` — accepts exactly 20 images and returns an encrypted face embedding when at least 15 pass validation.
- `POST /internal/face/recognize` — accepts a JPEG frame and JSON roster, then returns detected roster matches.

## Tests

```bash
python -m unittest discover -v
```

Optional tuning variables are `FACE_MATCH_MAX_DISTANCE`, `FACE_MATCH_AMBIGUITY_MARGIN`, and `FACE_INFERENCE_CONCURRENCY`.
