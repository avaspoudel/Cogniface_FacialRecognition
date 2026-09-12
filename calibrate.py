"""
calibrate.py

Utility to help you pick (and justify, in your NFR-3 test evidence) a
real Euclidean-distance recognition threshold.

The correct cutoff depends on the camera, lighting, and registration
images. This script measures dlib's native Euclidean distance.

Usage:
    python calibrate.py genuine_dir/ impostor_dir/

Where:
    genuine_dir/   contains several photos of the SAME person
                   (e.g. different angles from one registration session)
    impostor_dir/  contains one photo each of several DIFFERENT people

It prints the min/mean/max Euclidean distance for:
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

    genuine_eucl = []
    for i in range(len(genuine_embeddings)):
        for j in range(i + 1, len(genuine_embeddings)):
            genuine_eucl.append(fe.euclidean_distance(genuine_embeddings[i], genuine_embeddings[j]))

    impostor_eucl = []
    reference = genuine_embeddings[0]
    for emb in impostor_embeddings:
        impostor_eucl.append(fe.euclidean_distance(reference, emb))

    def report(name, values):
        print(f"  {name}: min={min(values):.4f} mean={mean(values):.4f} max={max(values):.4f}")

    print("\n=== Euclidean distance (lower = more similar) ===")
    report("genuine pairs ", genuine_eucl)
    report("impostor pairs", impostor_eucl)
    suggested = (max(genuine_eucl) + min(impostor_eucl)) / 2
    print(f"  -> suggested FACE_MATCH_MAX_DISTANCE: {suggested:.4f}")
    print("  (dlib's typical rule of thumb: distance < 0.6 = same person)")


if __name__ == "__main__":
    main()
