"""Isolated writer tests, also discoverable by pytest.

The fake below is ONLY an unmapped test object. These tests prove call/validation
behaviour, not PostgreSQL transactions, migrations, A's services, or durability.
"""

from dataclasses import dataclass
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from app.services import audit


@dataclass
class FakeRow:
    id: UUID
    flag_id: UUID
    environment: str | None
    action: str
    actor: str
    before_state: dict | None
    after_state: dict


def flag_snapshot(description="Before", archived=False):
    return {"key": "new-checkout", "description": description, "archived": archived}


def config_snapshot(initial_version=1, **changes):
    result = {"enabled": False, "target_groups": [], "rollout_percentage": 0, "version": initial_version}
    result.update(changes)
    return result


class WriterTests(TestCase):
    def setUp(self):
        self.session = Mock(spec=["add", "flush", "commit", "rollback", "begin", "begin_nested"])
        self.identifier = uuid4()
        self.model = patch.object(audit, "_load_audit_model", return_value=FakeRow)
        self.model.start()
        self.addCleanup(self.model.stop)

    def record(self, **changes):
        arguments = dict(
            session=self.session, flag_id=self.identifier, environment=None,
            action="FLAG_CREATED", actor="shared-admin", before_state=None,
            after_state=flag_snapshot(),
        )
        arguments.update(changes)
        result = audit.record_change(**arguments)
        self.assertIsNone(result)
        return self.session.add.call_args.args[0]

    def assert_no_transaction_control(self):
        for method in ("commit", "rollback", "begin", "begin_nested"):
            getattr(self.session, method).assert_not_called()

    def test_adds_and_flushes_exactly_one_row(self):
        row = self.record()
        self.session.add.assert_called_once_with(row)
        self.session.flush.assert_called_once_with()
        self.assertIsInstance(row.id, UUID)
        self.assertEqual(row.flag_id, self.identifier)
        self.assertIsNone(row.before_state)
        self.assertEqual(row.actor, "shared-admin")
        self.assert_no_transaction_control()

    def test_seed_actor_is_explicit_and_creation_only(self):
        self.assertEqual(self.record(actor="seed").actor, "seed")
        with self.assertRaises(audit.AuditValidationError):
            self.record(actor="seed", action="FLAG_UPDATED", before_state=flag_snapshot())

    def test_accepts_a_uuid_string(self):
        self.assertEqual(self.record(flag_id=str(self.identifier)).flag_id, self.identifier)

    def test_validates_before_model_loading_or_session_access(self):
        with patch.object(audit, "_load_audit_model") as model:
            with self.assertRaises(audit.AuditValidationError):
                self.record(action="NOT_AN_ACTION")
        model.assert_not_called()
        self.session.add.assert_not_called()
        self.session.flush.assert_not_called()

    def test_flush_failure_propagates_to_transaction_owner(self):
        failure = RuntimeError("synthetic flush failure")
        self.session.flush.side_effect = failure
        with self.assertRaises(RuntimeError) as result:
            self.record()
        self.assertIs(result.exception, failure)
        self.assert_no_transaction_control()

    def test_add_failure_is_not_swallowed(self):
        failure = RuntimeError("synthetic add failure")
        self.session.add.side_effect = failure
        with self.assertRaises(RuntimeError) as result:
            self.record()
        self.assertIs(result.exception, failure)
        self.session.flush.assert_not_called()
        self.assert_no_transaction_control()

    def test_copies_and_sorts_snapshots_without_mutating_inputs(self):
        before = config_snapshot(target_groups=["zeta", "beta"])
        after = config_snapshot(2, enabled=True, target_groups=["zeta", "beta"])
        row = self.record(environment="staging", action="CONFIG_UPDATED", before_state=before, after_state=after)
        self.assertEqual(row.before_state["target_groups"], ["beta", "zeta"])
        self.assertEqual(after["target_groups"], ["zeta", "beta"])
        before["target_groups"].append("later")
        after["target_groups"].append("later")
        self.assertEqual(row.after_state["target_groups"], ["beta", "zeta"])
        self.assertEqual(row.before_state["target_groups"], ["beta", "zeta"])

    def test_successful_unchanged_configuration_still_has_an_event(self):
        row = self.record(environment="production", action="CONFIG_UPDATED",
                          before_state=config_snapshot(), after_state=config_snapshot(2))
        self.assertEqual(row.after_state["version"], 2)
        self.session.flush.assert_called_once()

    def test_all_documented_action_shapes(self):
        cases = [
            dict(action="FLAG_CREATED", before_state=None, after_state=flag_snapshot()),
            dict(action="FLAG_UPDATED", before_state=flag_snapshot(), after_state=flag_snapshot("After")),
            dict(action="FLAG_ARCHIVED", before_state=flag_snapshot(), after_state=flag_snapshot(archived=True)),
            dict(action="CONFIG_UPDATED", environment="staging", before_state=config_snapshot(), after_state=config_snapshot(2)),
        ]
        for case in cases:
            with self.subTest(action=case["action"]):
                self.session.reset_mock()
                self.assertEqual(self.record(**case).action, case["action"])
                self.session.add.assert_called_once()
                self.session.flush.assert_called_once()
                self.assert_no_transaction_control()

    def test_rejects_invalid_action_actor_identifier_and_environment(self):
        cases = [
            {"action": "EVALUATED"}, {"action": []}, {"actor": "individual-admin"},
            {"actor": []}, {"flag_id": True}, {"flag_id": "bad-uuid"},
            {"environment": "staging"},
            {"action": "CONFIG_UPDATED", "environment": None, "before_state": config_snapshot(), "after_state": config_snapshot(2)},
            {"action": "CONFIG_UPDATED", "environment": "preview", "before_state": config_snapshot(), "after_state": config_snapshot(2)},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.session.reset_mock()
                with self.assertRaises(audit.AuditValidationError):
                    self.record(**case)
                self.session.add.assert_not_called()
                self.session.flush.assert_not_called()

    def test_rejects_invalid_configuration_types_and_bounds(self):
        invalid = [
            {"enabled": "true"}, {"enabled": 1},
            {"rollout_percentage": True}, {"rollout_percentage": "25"},
            {"rollout_percentage": -1}, {"rollout_percentage": 101}, {"rollout_percentage": 1.5},
            {"version": True}, {"version": "2"}, {"version": 0}, {"version": 3},
            {"target_groups": "beta"}, {"target_groups": ["beta", "beta"]},
            {"target_groups": [""]}, {"target_groups": [" beta"]},
            {"target_groups": ["beta\n"]}, {"target_groups": ["bad\x00group"]},
            {"target_groups": ["bad\x7fgroup"]}, {"target_groups": [42]},
            {"target_groups": ["x" * 65]}, {"target_groups": [str(i) for i in range(21)]},
        ]
        for change in invalid:
            with self.subTest(change=change):
                self.session.reset_mock()
                with self.assertRaises(audit.AuditValidationError):
                    self.record(environment="staging", action="CONFIG_UPDATED", before_state=config_snapshot(), after_state=config_snapshot(2, **change))
                self.session.add.assert_not_called()

    def test_rollout_boundaries_are_valid(self):
        for percentage in (0, 100):
            with self.subTest(percentage=percentage):
                row = self.record(environment="staging", action="CONFIG_UPDATED", before_state=config_snapshot(), after_state=config_snapshot(2, rollout_percentage=percentage))
                self.assertEqual(row.after_state["rollout_percentage"], percentage)

    def test_group_limit_and_case_sensitivity(self):
        groups = [f"g{i:02}" for i in range(18)] + ["beta", "Beta"]
        row = self.record(environment="staging", action="CONFIG_UPDATED", before_state=config_snapshot(), after_state=config_snapshot(2, target_groups=groups))
        self.assertEqual(len(row.after_state["target_groups"]), 20)
        self.assertIn("Beta", row.after_state["target_groups"])
        self.assertIn("beta", row.after_state["target_groups"])

    def test_rejects_invalid_flag_snapshot_and_transitions(self):
        invalid = [
            {"after_state": {}}, {"after_state": None},
            {"after_state": dict(flag_snapshot(), key="Bad-Key")},
            {"after_state": dict(flag_snapshot(), key="good\n")},
            {"after_state": dict(flag_snapshot(), description="x" * 501)},
            {"after_state": dict(flag_snapshot(), archived="false")},
            {"after_state": flag_snapshot(archived=True)},
            {"before_state": flag_snapshot()},
            {"action": "FLAG_UPDATED", "before_state": None},
            {"action": "FLAG_UPDATED", "before_state": flag_snapshot(), "after_state": dict(flag_snapshot(), key="different")},
            {"action": "FLAG_UPDATED", "before_state": flag_snapshot(archived=True)},
            {"action": "FLAG_UPDATED", "before_state": flag_snapshot(), "after_state": flag_snapshot(archived=True)},
            {"action": "FLAG_ARCHIVED", "before_state": flag_snapshot(), "after_state": flag_snapshot()},
            {"action": "FLAG_ARCHIVED", "before_state": flag_snapshot(), "after_state": flag_snapshot("Changed", archived=True)},
        ]
        for case in invalid:
            with self.subTest(case=case):
                self.session.reset_mock()
                with self.assertRaises(audit.AuditValidationError):
                    self.record(**case)
                self.session.add.assert_not_called()

    def test_extra_secret_fields_are_rejected_without_echoing_values(self):
        sentinel = "SYNTHETIC-DO-NOT-LOG-THIS"
        for field in ("Authorization", "ADMIN_TOKEN", "request_headers", "EVALUATION_API_KEY"):
            with self.subTest(field=field):
                with self.assertRaises(audit.AuditValidationError) as result:
                    self.record(after_state=dict(flag_snapshot(), **{field: sentinel}))
                self.assertNotIn(sentinel, str(result.exception))
                self.assertNotIn(field, str(result.exception))

    def test_missing_shared_model_is_not_replaced_with_a_fake(self):
        with patch.object(audit, "_load_audit_model", side_effect=audit.AuditModelUnavailable("Shared model unavailable")):
            with self.assertRaises(audit.AuditModelUnavailable):
                self.record()
        self.session.add.assert_not_called()
