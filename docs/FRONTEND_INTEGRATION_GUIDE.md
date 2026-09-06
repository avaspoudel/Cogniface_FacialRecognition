# Application Integration

The React frontend must communicate only with the main Express API.

## Registration

1. The student calls `GET /api/face/me/status` through Express.
2. The browser captures 20 guided JPEG photos.
3. It submits them as multipart field `images` to `POST /api/face/register`.
4. Express authenticates the student and calls this private Python service.
5. Express stores the returned encrypted embedding in PostgreSQL.

The browser never receives an embedding or calls Python directly.

## Attendance

1. The lecturer opens an Express-owned attendance session.
2. The browser captures at most approximately one frame per second.
3. It submits one JPEG as multipart field `frame` to
   `POST /api/attendance/sessions/:sessionId/frames`.
4. Express validates session ownership and builds the authorized enrolled roster.
5. Python returns proposed matches.
6. Express revalidates the session/enrollments and writes missing attendance records.

Only one frame request should be in flight. Stop media tracks and abort an active
request when scanning stops, the page unmounts, or the attendance session closes.
