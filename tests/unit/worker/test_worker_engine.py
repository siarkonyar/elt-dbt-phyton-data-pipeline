"""get_engine builds a URL only. create_engine does not connect, so no
Postgres is needed here."""
import pytest


def test_the_engine_points_at_the_compose_postgres_by_default(worker_db):
    engine = worker_db.get_engine({"DESTINATION_POSTGRES_PASSWORD": "secret"})

    assert engine.url.host == "destination_postgres"
    assert engine.url.port == 5432
    assert engine.url.database == "destination_db"
    assert engine.url.username == "postgres"
    assert engine.url.password == "secret"


def test_every_part_of_the_address_can_be_overridden(worker_db):
    engine = worker_db.get_engine(
        {
            "DESTINATION_POSTGRES_HOST": "localhost",
            "DESTINATION_POSTGRES_PORT": "5434",
            "DESTINATION_POSTGRES_DB": "test_db",
            "DESTINATION_POSTGRES_USER": "tester",
            "DESTINATION_POSTGRES_PASSWORD": "secret",
        }
    )

    assert (engine.url.host, engine.url.port) == ("localhost", 5434)
    assert (engine.url.database, engine.url.username) == ("test_db", "tester")


def test_a_missing_password_says_where_to_look(worker_db):
    with pytest.raises(RuntimeError, match="worker service"):
        worker_db.get_engine({})
