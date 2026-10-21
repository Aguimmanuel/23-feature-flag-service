from app.models import AuditLog


def database_test_writer(session, flag_id, environment, action, actor, before_state, after_state):
    """Test-only transactional writer. Not a production audit implementation."""
    session.add(AuditLog(
        flag_id=flag_id, environment=environment, action=action, actor=actor,
        before_state=before_state, after_state=after_state,
    ))
    session.flush()


