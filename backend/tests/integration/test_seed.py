from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.audit_contract import AuditWriterUnavailable
from app.models import AuditLog, Flag, FlagEnvironment
from app.seed import main, seed_database
from tests.audit_helpers import database_test_writer


def test_seed_defaults_and_create_audits(session_factory):
    result = seed_database(session_factory, database_test_writer)
    assert result.created == ("new-checkout", "search-preview")
    with session_factory() as session:
        flags = session.scalars(select(Flag).order_by(Flag.key)).all()
        assert len(flags) == 2
        assert session.scalar(select(func.count()).select_from(FlagEnvironment)) == 6
        flag = flags[0]
        staging = session.get(FlagEnvironment, (flag.id, "staging"))
        development = session.get(FlagEnvironment, (flag.id, "development"))
        production = session.get(FlagEnvironment, (flag.id, "production"))
        assert (staging.enabled, staging.target_groups, staging.rollout_percentage, staging.version) == (True, ["beta"], 25, 1)
        assert development.enabled and development.rollout_percentage == 100
        assert not production.enabled and production.rollout_percentage == 0
        audits = session.scalars(select(AuditLog)).all()
        assert len(audits) == 2
        assert all(a.actor == "seed" and a.before_state is None for a in audits)


def test_rerun_preserves_existing_edits_archival_and_versions(session_factory):
    seed_database(session_factory, database_test_writer)
    with session_factory.begin() as session:
        flag = session.scalar(select(Flag).where(Flag.key == "new-checkout"))
        flag.archived = True
        flag.description = "Do not reset this"
        config = session.get(FlagEnvironment, (flag.id, "staging"))
        config.rollout_percentage = 73
        config.version = 4
    result = seed_database(session_factory, database_test_writer)
    assert result.created == () and result.skipped == ("new-checkout", "search-preview")
    with session_factory() as session:
        flag = session.scalar(select(Flag).where(Flag.key == "new-checkout"))
        assert flag.archived and flag.description == "Do not reset this"
        config = session.get(FlagEnvironment, (flag.id, "staging"))
        assert (config.rollout_percentage, config.version) == (73, 4)
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 2


def test_seed_rolls_back_all_rows_when_audit_fails(session_factory):
    def failing_writer(**kwargs):
        database_test_writer(**kwargs)
        raise RuntimeError("simulated audit failure")
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        seed_database(session_factory, failing_writer)
    with session_factory() as session:
        for model in (Flag, FlagEnvironment, AuditLog):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_concurrent_seeds_are_serialized_without_duplicates(session_factory):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: seed_database(session_factory, database_test_writer), range(2)))
    assert sorted(len(result.created) for result in results) == [0, 2]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Flag)) == 2
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 2


def test_seed_cli_refuses_to_run_without_real_audit_writer(monkeypatch):
    def unavailable():
        raise AuditWriterUnavailable("The transactional audit writer is not integrated")
    monkeypatch.setattr("app.seed.load_audit_writer", unavailable)
    with pytest.raises(SystemExit, match="audit writer is not integrated"):
        main()
