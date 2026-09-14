"""Small test doubles for optional or expensive runtime dependencies."""

import sys
from types import ModuleType


def stub_face_recognition() -> None:
    """Avoid loading dlib models in tests that do not exercise face detection."""
    sys.modules.setdefault("face_recognition", ModuleType("face_recognition"))
