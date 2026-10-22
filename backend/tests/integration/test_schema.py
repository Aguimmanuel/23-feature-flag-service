from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, Base, Flag, FlagEnvironment
from tests.integration.conftest import migration_config


def test_migration_tables_match_orm_metadata(database_engine):
    with database_engine.connect() as connection:
        assert {"flags", "flag_environments", "audit_logs", "alembic_version"} <= set(inspect(connection).get_table_names())
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert differences == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        assert int(connection.scalar(text("SHOW server_version_num"))) // 10000 == 18


def test_initial_migration_downgrade_and_reupgrade(database_engine):
    with database_engine.begin() as connection:
        command.downgrade(migration_config(connection), "base")
        assert "flags" not in inspect(connection).get_table_names()
        command.upgrade(migration_config(connection), "head")
        assert "flags" in inspect(connection).get_table_names()


def test_defaults_roundtrip_and_timezone(session_factory):
    with session_factory.begin() as session:
        flag = Flag(key="default-flag")
        session.add(flag)
        session.flush()
        session.add(FlagEnvironment(flag_id=flag.id, environment="staging"))
        flag_id = flag.id
    with session_factory() as session:
        flag = session.get(Flag, flag_id)
        config = session.get(FlagEnvironment, (flag_id, "staging"))
        assert flag.description == "" and flag.archived is False
        assert flag.created_at.tzinfo is not None
        assert config.enabled is False and config.target_groups == []
        assert config.version == 1 and config.rollout_percentage == 0
        assert config.updated_at.tzinfo is not None


@pytest.mark.parametrize("changes", [
    {"environment": "invalid"}, {"rollout_percentage": -1}, {"rollout_percentage": 101},
    {"version": 0}, {"target_groups": [str(i) for i in range(21)]}, {"target_groups": [None]},
])
def test_database_config_constraints(session_factory, changes):
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            flag = Flag(key="constraint-flag")
            session.add(flag)
            session.flush()
            values = {"flag_id": flag.id, "environment": "staging", **changes}
            session.add(FlagEnvironment(**values))
            session.flush()


@pytest.mark.parametrize("key", ["Uppercase", "bad key", "1starts-with-number", ""])
def test_database_key_format_constraint(session_factory, key):
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(Flag(key=key))
            session.flush()


def test_key_unique_even_when_archived(session_factory):
    with session_factory.begin() as session:
        session.add(Flag(key="reserved", archived=True))
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(Flag(key="reserved"))
            session.flush()


def test_duplicate_environment_and_orphan_config_are_rejected(session_factory):
    with session_factory.begin() as session:
        flag = Flag(key="parent")
        session.add(flag)
        session.flush()
        flag_id = flag.id
        session.add(FlagEnvironment(flag_id=flag_id, environment="staging"))
    for child_id in (flag_id, uuid4()):
        with pytest.raises(IntegrityError):
            with session_factory.begin() as session:
                session.add(FlagEnvironment(flag_id=child_id, environment="staging"))
                session.flush()


@pytest.mark.parametrize("action,environment", [
    ("UNKNOWN", None), ("CONFIG_UPDATED", None), ("FLAG_CREATED", "staging"),
    ("CONFIG_UPDATED", "invalid"),
])
def test_audit_constraints(session_factory, action, environment):
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            flag = Flag(key="audit-parent")
            session.add(flag)
            session.flush()
            session.add(AuditLog(flag_id=flag.id, action=action, environment=environment, after_state={}))
            session.flush()


def test_audit_json_roundtrip_and_foreign_key_restrict(session_factory):
    with session_factory.begin() as session:
        flag = Flag(key="audit-json")
        session.add(flag)
        session.flush()
        flag_id = flag.id
        session.add(AuditLog(flag_id=flag_id, action="FLAG_CREATED", before_state=None, after_state={"archived": False}))
    with session_factory() as session:
        audit = session.scalar(select(AuditLog))
        assert audit.before_state is None
        assert audit.after_state == {"archived": False}
        assert audit.actor == "shared-admin"
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(delete(Flag).where(Flag.id == flag_id))


def test_missing_after_snapshot_is_rejected(session_factory):
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            flag = Flag(key="missing-after")
            session.add(flag)
            session.flush()
            session.add(AuditLog(flag_id=flag.id, action="FLAG_CREATED", after_state=None))
            session.flush()


def test_utf8_group_and_description_roundtrip(session_factory):
    with session_factory.begin() as session:
        flag = Flag(key="unicode-data", description="Checkout — préparation")
        session.add(flag)
        session.flush()
        flag_id = flag.id
        session.add(FlagEnvironment(flag_id=flag_id, environment="staging", target_groups=["équipe", "تجربة"]))
    with session_factory() as session:
        assert session.get(Flag, flag_id).description == "Checkout — préparation"
        assert session.get(FlagEnvironment, (flag_id, "staging")).target_groups == ["équipe", "تجربة"]
