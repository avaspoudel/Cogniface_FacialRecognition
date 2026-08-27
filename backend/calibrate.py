"""
calibrate.py

Utility to help you pick (and justify, in your NFR-3 test evidence) a
real recognition threshold instead of trusting the pseudocode's 0.85
default blindly.

`face_recognition`'s embeddings are tuned for *Euclidean* distance, not
cosine similarity, so the right cosine cutoff isn't obvious up front --
it depends on your camera, lighting, and how the 15 registration shots
are captured. This script measures both metrics on your own images so
you can defend whatever number you put in the report.

Usage:
    python calibrate.py genuine_dir/ impostor_dir/

Where:
    genuine_dir/   contains several photos of the SAME person
                   (e.g. different angles from one registration session)
    impostor_dir/  contains one photo each of several DIFFERENT people

It prints the min/mean/max cosine similarity and Euclidean distance for:
    - "genuine" pairs   (same person compared to themselves)
    - "impostor" pairs  (that person compared to everyone else)

A good threshold sits in the gap between the impostor max and the
genuine min. If there's no gap (they overlap), that's worth reporting
as a real accuracy/security trade-off in your NFR-3 evidence, not a bug
to hide.
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean

import face_engine as fe


def load_embedding(path: Path):
    image = _load_image(path)
    faces = fe.detect_faces(image)
    if len(faces) != 1:
        print(f"  [skip] {path.name}: expected 1 face, found {len(faces)}")
        return None
    return fe.generate_embedding(image, faces[0])


def _load_image(path: Path):
    import cv2

    bgr = cv2.imread(str(path))
    if bgr is None:
        raise ValueError(f"Could not read image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    genuine_dir = Path(sys.argv[1])
    impostor_dir = Path(sys.argv[2])

    print(f"Loading genuine (same-person) images from {genuine_dir} ...")
    genuine_embeddings = [e for e in (load_embedding(p) for p in sorted(genuine_dir.glob("*"))) if e is not None]

    print(f"Loading impostor (different-people) images from {impostor_dir} ...")
    impostor_embeddings = [e for e in (load_embedding(p) for p in sorted(impostor_dir.glob("*"))) if e is not None]

    if len(genuine_embeddings) < 2:
        print("Need at least 2 genuine images to form a pair. Aborting.")
        sys.exit(1)
    if len(impostor_embeddings) < 1:
        print("Need at least 1 impostor image. Aborting.")
        sys.exit(1)

    genuine_cos, genuine_eucl = [], []
    for i in range(len(genuine_embeddings)):
        for j in range(i + 1, len(genuine_embeddings)):
            genuine_cos.append(fe.cosine_similarity(genuine_embeddings[i], genuine_embeddings[j]))
            genuine_eucl.append(fe.euclidean_distance(genuine_embeddings[i], genuine_embeddings[j]))

    impostor_cos, impostor_eucl = [], []
    reference = genuine_embeddings[0]
    for emb in impostor_embeddings:
        impostor_cos.append(fe.cosine_similarity(reference, emb))
        impostor_eucl.append(fe.euclidean_distance(reference, emb))

    def report(name, values):
        print(f"  {name}: min={min(values):.4f} mean={mean(values):.4f} max={max(values):.4f}")

    print("\n=== Cosine similarity (higher = more similar) ===")
    report("genuine pairs ", genuine_cos)
    report("impostor pairs", impostor_cos)
    suggested = (min(genuine_cos) + max(impostor_cos)) / 2
    print(f"  -> suggested cosine threshold (midpoint of the gap): {suggested:.4f}")
    print(f"     (current RECOGNITION_THRESHOLD in face_engine.py is {fe.RECOGNITION_THRESHOLD})")

    print("\n=== Euclidean distance (lower = more similar) ===")
    report("genuine pairs ", genuine_eucl)
    report("impostor pairs", impostor_eucl)
    print("  (dlib's typical rule of thumb: distance < 0.6 = same person)")


if __name__ == "__main__":
    main()
