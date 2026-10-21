import pytest
from pydantic import ValidationError

from app.schemas import EnvironmentUpdate, EvaluationRequest, FlagCreate, FlagUpdate


def config(**changes):
    return {"enabled": True, "target_groups": [], "rollout_percentage": 25, "version": 1, **changes}


@pytest.mark.parametrize("key", ["a", "new-checkout", "search_preview", "a" * 64])
def test_valid_keys(key):
    assert FlagCreate(key=key).description == ""


@pytest.mark.parametrize("key", ["", "1flag", "Flag", " flag", "flag ", "a" * 65, "flag\n", 3, None])
def test_invalid_keys(key):
    with pytest.raises(ValidationError):
        FlagCreate(key=key)


@pytest.mark.parametrize("percentage", [-1, 101, 1.5, True, "25", None])
def test_percentage_rejects_bad_values_and_coercion(percentage):
    with pytest.raises(ValidationError):
        EnvironmentUpdate(**config(rollout_percentage=percentage))


@pytest.mark.parametrize("percentage", [0, 25, 100])
def test_percentage_accepts_integer_range(percentage):
    assert EnvironmentUpdate(**config(rollout_percentage=percentage)).rollout_percentage == percentage


@pytest.mark.parametrize("groups", [
    ["beta", "beta"], [""], [" beta"], ["beta "], ["a\nb"], ["a\x00b"],
    ["a\x7fb"], ["x" * 65], [str(i) for i in range(21)], "beta", [1], None,
])
def test_invalid_groups(groups):
    with pytest.raises(ValidationError):
        EnvironmentUpdate(**config(target_groups=groups))


def test_group_matching_context_remains_case_sensitive():
    data = EnvironmentUpdate(**config(target_groups=["beta", "Beta"]))
    assert data.sorted_target_groups() == ["Beta", "beta"]
    assert data.target_groups == ["beta", "Beta"]


@pytest.mark.parametrize("changes", [
    {"enabled": "true"}, {"enabled": 1}, {"version": 0}, {"version": True},
    {"version": "1"}, {"unexpected": "value"},
])
def test_configuration_is_strict(changes):
    with pytest.raises(ValidationError):
        EnvironmentUpdate(**config(**changes))


@pytest.mark.parametrize("field", ["enabled", "target_groups", "rollout_percentage", "version"])
def test_configuration_requires_all_editable_fields(field):
    data = config()
    del data[field]
    with pytest.raises(ValidationError):
        EnvironmentUpdate(**data)


@pytest.mark.parametrize("user_id", ["", " user", "user ", "a\nb", "a" * 129, 12])
def test_user_context_validation(user_id):
    with pytest.raises(ValidationError):
        EvaluationRequest(flag_key="checkout", environment="staging", user={"id": user_id})


def test_groups_default_empty_and_environment_is_fixed():
    data = EvaluationRequest(flag_key="checkout", environment="staging", user={"id": "user-001"})
    assert data.user.groups == []
    with pytest.raises(ValidationError):
        EvaluationRequest(flag_key="checkout", environment="qa", user={"id": "user-001"})


@pytest.mark.parametrize("model,data", [
    (FlagCreate, {"key": "checkout", "description": 4}),
    (FlagCreate, {"key": "checkout", "description": "a" * 501}),
    (FlagCreate, {"key": "checkout", "enabled": True}),
    (FlagUpdate, {}),
    (FlagUpdate, {"description": "x", "key": "new-key"}),
])
def test_description_and_extra_fields(model, data):
    with pytest.raises(ValidationError):
        model(**data)
