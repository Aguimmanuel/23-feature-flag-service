import types
from unittest.mock import patch

import pytest

from app.audit_contract import AuditWriterUnavailable, load_audit_writer


def test_missing_audit_writer_is_not_silently_replaced():
    with patch("app.audit_contract.import_module", side_effect=ModuleNotFoundError(name="app.services.audit")):
        with pytest.raises(AuditWriterUnavailable):
            load_audit_writer()


def test_missing_nested_dependency_is_not_misreported_as_missing_writer():
    with patch("app.audit_contract.import_module", side_effect=ModuleNotFoundError(name="another_dependency")):
        with pytest.raises(ModuleNotFoundError):
            load_audit_writer()


def test_module_without_expected_function_is_rejected():
    with patch("app.audit_contract.import_module", return_value=types.SimpleNamespace()):
        with pytest.raises(AuditWriterUnavailable):
            load_audit_writer()
