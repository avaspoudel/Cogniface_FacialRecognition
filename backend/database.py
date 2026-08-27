"""
database.py

SQLite persistence layer standing in for the cloud database described in
the proposal (e.g. RDS/Cloud SQL). Tables map directly onto the entities
referenced in the pseudocode: Students, FacialFeatures, AttendanceSessions,
AttendanceRecords, plus minimal Classes/Enrollment tables so the
attendance flow (FR-6) has something realistic to query against.

Kept as plain sqlite3 (no ORM) so the mapping between this code and the
pseudocode in the proposal stays easy to read line-by-line -- this file
is meant to be readable next to section 5 of the report.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, List, Optional

DB_PATH = Path(__file__).parent / "storage" / "attendance.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT,
    face_registered INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facial_features (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id          TEXT NOT NULL UNIQUE REFERENCES students(student_id),
    storage_path        TEXT NOT NULL,
    no_of_photos        INTEGER NOT NULL,
    encrypted_embedding BLOB NOT NULL,
    registration_date   TEXT NOT NULL,
    last_updated        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    class_id    TEXT PRIMARY KEY,
    class_name  TEXT NOT NULL,
    lecturer_id TEXT NOT NULL,
    start_time  TEXT NOT NULL,   -- HH:MM, 24h
    end_time    TEXT NOT NULL    -- HH:MM, 24h
);

CREATE TABLE IF NOT EXISTS enrollments (
    class_id   TEXT NOT NULL REFERENCES classes(class_id),
    student_id TEXT NOT NULL REFERENCES students(student_id),
    status     TEXT NOT NULL DEFAULT 'On Going',
    PRIMARY KEY (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS attendance_sessions (
    session_id  TEXT PRIMARY KEY,
    class_id    TEXT NOT NULL REFERENCES classes(class_id),
    lecturer_id TEXT NOT NULL,
    status      TEXT NOT NULL,   -- 'In Progress' | 'Closed'
    start_time  TEXT NOT NULL,
    end_time    TEXT
);

CREATE TABLE IF NOT EXISTS attendance_records (
    attendance_id       TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES attendance_sessions(session_id),
    student_id           TEXT NOT NULL REFERENCES students(student_id),
    class_id             TEXT NOT NULL REFERENCES classes(class_id),
    attendance_datetime  TEXT NOT NULL,
    attendance_status    TEXT NOT NULL,   -- 'Present' | 'Late' | 'Absent'
    recognition_method   TEXT NOT NULL,   -- 'Automated' | 'Manual'
    confidence            REAL,
    marked_by             TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    UNIQUE (session_id, student_id)
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

def create_student(student_id: str, name: str, email: Optional[str] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO students (student_id, name, email, face_registered, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (student_id, name, email, _now()),
        )


def get_student(student_id: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
        return cur.fetchone()


def set_face_registered(student_id: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE students SET face_registered = 1 WHERE student_id = ?", (student_id,))


def list_students() -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM students ORDER BY created_at").fetchall()


# ---------------------------------------------------------------------------
# Facial features
# ---------------------------------------------------------------------------

def save_facial_record(student_id: str, storage_path: str, no_of_photos: int, encrypted_embedding: bytes) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO facial_features "
            "(student_id, storage_path, no_of_photos, encrypted_embedding, registration_date, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, storage_path, no_of_photos, encrypted_embedding, now, now),
        )


def get_facial_record(student_id: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM facial_features WHERE student_id = ?", (student_id,))
        return cur.fetchone()


def get_facial_records_for_class(class_id: str) -> List[sqlite3.Row]:
    """FR-6.2.11: retrieve encrypted facial data for enrolled students."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT s.student_id, s.name AS student_name, ff.encrypted_embedding
            FROM enrollments e
            JOIN students s ON s.student_id = e.student_id
            JOIN facial_features ff ON ff.student_id = s.student_id
            WHERE e.class_id = ? AND e.status = 'On Going'
            """,
            (class_id,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Classes / enrollment (minimal support scaffolding for the demo)
# ---------------------------------------------------------------------------

def create_class(class_id: str, class_name: str, lecturer_id: str, start_time: str, end_time: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO classes (class_id, class_name, lecturer_id, start_time, end_time) "
            "VALUES (?, ?, ?, ?, ?)",
            (class_id, class_name, lecturer_id, start_time, end_time),
        )


def get_class(class_id: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM classes WHERE class_id = ?", (class_id,)).fetchone()


def enroll_student(class_id: str, student_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO enrollments (class_id, student_id, status) VALUES (?, ?, 'On Going')",
            (class_id, student_id),
        )


def get_enrolled_students(class_id: str) -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT s.student_id, s.name
            FROM enrollments e JOIN students s ON s.student_id = e.student_id
            WHERE e.class_id = ? AND e.status = 'On Going'
            """,
            (class_id,),
        ).fetchall()


# ---------------------------------------------------------------------------
# Attendance sessions
# ---------------------------------------------------------------------------

def create_attendance_session(class_id: str, lecturer_id: str) -> str:
    session_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO attendance_sessions (session_id, class_id, lecturer_id, status, start_time, end_time) "
            "VALUES (?, ?, ?, 'In Progress', ?, NULL)",
            (session_id, class_id, lecturer_id, _now()),
        )
    return session_id


def get_session(session_id: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM attendance_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()


def close_session(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE attendance_sessions SET status = 'Closed', end_time = ? WHERE session_id = ?",
            (_now(), session_id),
        )


# ---------------------------------------------------------------------------
# Attendance records
# ---------------------------------------------------------------------------

def get_existing_attendance_record(session_id: str, student_id: str) -> Optional[sqlite3.Row]:
    """FR-6.2.16: prevent duplicate attendance marking in the same session."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM attendance_records WHERE session_id = ? AND student_id = ?",
            (session_id, student_id),
        ).fetchone()


def save_attendance_record(
    session_id: str,
    student_id: str,
    class_id: str,
    status: str,
    method: str,
    marked_by: str,
    confidence: Optional[float] = None,
) -> str:
    attendance_id = str(uuid.uuid4())
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO attendance_records
                (attendance_id, session_id, student_id, class_id, attendance_datetime,
                 attendance_status, recognition_method, confidence, marked_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id, student_id) DO UPDATE SET
                attendance_status = excluded.attendance_status,
                recognition_method = excluded.recognition_method,
                confidence = excluded.confidence
            """,
            (attendance_id, session_id, student_id, class_id, now, status, method, confidence, marked_by, now),
        )
    return attendance_id


def mark_absentees(session_id: str, class_id: str, marked_by: str) -> int:
    """FR-6.3.6: mark any enrolled student with no record yet as absent."""
    enrolled = get_enrolled_students(class_id)
    count = 0
    for student in enrolled:
        if get_existing_attendance_record(session_id, student["student_id"]) is None:
            save_attendance_record(
                session_id, student["student_id"], class_id,
                status="Absent", method="Automated", marked_by=marked_by,
            )
            count += 1
    return count


def get_session_records(session_id: str) -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT ar.*, s.name AS student_name
            FROM attendance_records ar JOIN students s ON s.student_id = ar.student_id
            WHERE ar.session_id = ?
            ORDER BY ar.attendance_datetime
            """,
            (session_id,),
        ).fetchall()


def get_attendance_for_student(student_id: str) -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT ar.*, c.class_name
            FROM attendance_records ar JOIN classes c ON c.class_id = ar.class_id
            WHERE ar.student_id = ?
            ORDER BY ar.attendance_datetime DESC
            """,
            (student_id,),
        ).fetchall()
