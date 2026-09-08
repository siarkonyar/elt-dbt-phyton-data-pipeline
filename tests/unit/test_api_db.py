import pytest

def test_a_missing_password_is_rejected(api_db):
    with pytest.raises(RuntimeError):
        api_db.get_engine({})

def test_an_empty_password_is_rejected(api_db):
    with pytest.raises(RuntimeError):
        api_db.get_engine({"DESTINATION_POSTGRES_PASSWORD": ""})

def test_the_defaults_are_used_when_only_a_password_is_given(api_db):
    engine = api_db.get_engine({"DESTINATION_POSTGRES_PASSWORD": "123"})
    assert engine.url.host == "destination_postgres"
    assert engine.url.database == "destination_db"
    assert engine.url.port == 5432

def test_the_environment_overrides_the_defaults(api_db):
    engine = api_db.get_engine({
        "DESTINATION_POSTGRES_PASSWORD": "123",
        "DESTINATION_POSTGRES_DB": "test_db",
        "DESTINATION_POSTGRES_HOST": "test_host"
    })
    assert engine.url.host == "test_host"
    assert engine.url.database == "test_db"