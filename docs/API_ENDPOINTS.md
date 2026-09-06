# Private Inference API

Every POST request requires:

```http
X-Internal-Service-Token: <shared service secret>
```

These endpoints are for the Node/Express backend, not browsers.

## `GET /internal/health`

Returns whether the service token and encryption key are configured.

## `POST /internal/face/register`

Multipart request with exactly 20 JPEG files using the repeated field `images`.
Each file is limited to 1 MB. At least 15 images must pass face-count, quality,
and pose validation.

Success returns an encrypted averaged embedding, accepted/rejected counts, and
per-image results. Image bytes are discarded after processing.

## `POST /internal/face/recognize`

Multipart fields:

- `frame`: one JPEG frame, at most 1 MB.
- `roster`: JSON containing authorized students and encrypted embeddings.

Roster shape:

```json
{
  "students": [
    {
      "studentId": "internal-student-uuid",
      "studentName": "Student Name",
      "encryptedEmbedding": "fernet-token"
    }
  ]
}
```

The response includes frame dimensions, detected-face count, processing time,
and unambiguous Euclidean-distance matches. It never writes attendance.
