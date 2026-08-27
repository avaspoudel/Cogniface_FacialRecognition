"""Pydantic request/response models for the API layer."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class StudentCreate(BaseModel):
    student_id: str
    name: str
    email: Optional[str] = None


class ClassCreate(BaseModel):
    class_id: str
    class_name: str
    lecturer_id: str
    start_time: str = Field(..., description="HH:MM, 24h, class start time")
    end_time: str = Field(..., description="HH:MM, 24h, class end time")


class EnrollRequest(BaseModel):
    class_id: str
    student_id: str


class FaceRegistrationRequest(BaseModel):
    student_id: str
    images: List[str] = Field(..., description="Base64-encoded (or data: URL) JPEG/PNG images, min 15")


class SessionStartRequest(BaseModel):
    class_id: str
    lecturer_id: str
    enforce_class_time: bool = Field(
        default=False,
        description="If true, reject session start outside the class's scheduled window (FR-6.1.3).",
    )


class FrameRequest(BaseModel):
    session_id: str
    class_id: str
    image_frame: str = Field(..., description="Base64-encoded (or data: URL) JPEG/PNG video frame")


class ManualAttendanceUpdate(BaseModel):
    session_id: str
    student_id: str
    status: str = Field(..., description="One of: Present, Absent, Late")
    marked_by: str
