"""Internal inference-service request schemas."""

from pydantic import BaseModel, Field


class RosterStudent(BaseModel):
    student_id: str = Field(alias="studentId")
    student_name: str = Field(alias="studentName")
    encrypted_embedding: str = Field(alias="encryptedEmbedding")


class RecognitionRoster(BaseModel):
    students: list[RosterStudent]
