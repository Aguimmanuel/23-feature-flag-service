"""The critical evaluation lookup reads only the requested environment once."""

from sqlalchemy import event

from app.models import Flag, FlagEnvironment
from app.repositories.flags import get_flag_with_environment


def test_single_joined_select_is_filtered_to_requested_environment(database_engine, session_factory):
    with session_factory.begin() as session:
        flag = Flag(key="joined-lookup")
        session.add(flag)
        session.flush()
        for environment in ("development", "staging", "production"):
            session.add(FlagEnvironment(flag_id=flag.id, environment=environment))
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, context.compiled_parameters))
    event.listen(database_engine, "before_cursor_execute", capture)
    try:
        with session_factory() as session:
            flag, config = get_flag_with_environment(session, "joined-lookup", "staging")
            assert flag.key == "joined-lookup" and config.environment == "staging"
    finally:
        event.remove(database_engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "staging" in statements[0][1][0].values()


def test_left_join_preserves_missing_configuration_distinction(session_factory):
    with session_factory.begin() as session:
        session.add(Flag(key="no-configuration"))
        session.add(Flag(key="archived-lookup", archived=True))
    with session_factory() as session:
        flag, config = get_flag_with_environment(session, "no-configuration", "staging")
        assert flag is not None and config is None
        assert get_flag_with_environment(session, "archived-lookup", "staging") == (None, None)
        assert get_flag_with_environment(session, "unknown", "staging") == (None, None)
