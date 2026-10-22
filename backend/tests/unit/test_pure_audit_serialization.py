from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from uuid import uuid4

from app.api.audit import serialize_entry
from app.services.audit import AuditValidationError


class SerializationTests(TestCase):
    def row(self, **changes):
        fields = dict(
            id=uuid4(), flag_id=uuid4(), environment=None, action="FLAG_CREATED",
            actor="shared-admin", before_state=None,
            after_state={"key": "new-checkout", "description": "Synthetic", "archived": False},
            created_at=datetime(2026, 1, 1, 13, tzinfo=timezone(timedelta(hours=1))),
            private_headers={"Authorization": "SYNTHETIC-SENTINEL"},
        )
        fields.update(changes)
        return SimpleNamespace(**fields)

    def test_exact_fields_and_utc_timestamp(self):
        row = self.row()
        result = serialize_entry(row, "new-checkout")
        self.assertEqual(set(result), {"id", "flag_key", "environment", "action", "actor", "before", "after", "created_at"})
        self.assertEqual(result["created_at"], "2026-01-01T12:00:00Z")
        self.assertEqual(result["id"], str(row.id))
        self.assertIsNone(result["before"])
        self.assertNotIn("SYNTHETIC-SENTINEL", str(result))

    def test_naive_or_missing_timestamp_is_rejected(self):
        for stamp in (datetime(2026, 1, 1), None, "2026-01-01T00:00:00Z"):
            with self.subTest(timestamp=stamp):
                with self.assertRaises(AuditValidationError):
                    serialize_entry(self.row(created_at=stamp), "new-checkout")

    def test_mismatching_key_is_rejected(self):
        with self.assertRaises(AuditValidationError):
            serialize_entry(self.row(), "other-flag")

    def test_unexpected_stored_fields_do_not_leak(self):
        row = self.row()
        row.after_state["ADMIN_TOKEN"] = "SYNTHETIC-SENTINEL"
        with self.assertRaises(AuditValidationError) as result:
            serialize_entry(row, "new-checkout")
        self.assertNotIn("SYNTHETIC-SENTINEL", str(result.exception))

    def test_invalid_identifier_is_rejected(self):
        with self.assertRaises(AuditValidationError):
            serialize_entry(self.row(id="not-a-uuid"), "new-checkout")
