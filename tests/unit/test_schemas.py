import unittest

from pydantic import ValidationError

from schemas import RecognitionRoster


class RecognitionRosterTests(unittest.TestCase):
    def test_accepts_api_field_names(self) -> None:
        roster = RecognitionRoster.model_validate({
            "students": [{
                "studentId": "student-1",
                "studentName": "Ada Lovelace",
                "encryptedEmbedding": "encrypted-value",
            }],
        })

        self.assertEqual(roster.students[0].student_id, "student-1")
        self.assertEqual(roster.students[0].student_name, "Ada Lovelace")

    def test_rejects_incomplete_student(self) -> None:
        with self.assertRaises(ValidationError):
            RecognitionRoster.model_validate({
                "students": [{"studentId": "student-1"}],
            })


if __name__ == "__main__":
    unittest.main()
