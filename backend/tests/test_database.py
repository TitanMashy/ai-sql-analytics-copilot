from collections.abc import Generator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.schema_metadata import get_schema_metadata
from app.db.seed import generate_seed_rows
from app.models.entities import Customer, Driver, Trip, Vehicle


@pytest.fixture
def database_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        yield session


def test_seed_generation_is_deterministic() -> None:
    first = generate_seed_rows()
    second = generate_seed_rows()

    assert first == second
    assert len(first[Customer]) == 100
    assert len(first[Vehicle]) == 1_000


def test_seed_relationship_choices_share_customer() -> None:
    rows = generate_seed_rows()
    vehicle_customers = {row["id"]: row["customer_id"] for row in rows[Vehicle]}
    driver_customers = {row["id"]: row["customer_id"] for row in rows[Driver]}

    assert all(
        vehicle_customers[trip["vehicle_id"]] == trip["customer_id"]
        and driver_customers[trip["driver_id"]] == trip["customer_id"]
        for trip in rows[Trip]
    )


def test_schema_metadata_lists_requested_relationships() -> None:
    tables = {table.name: table for table in get_schema_metadata()}

    assert set(tables) == {
        "customers",
        "drivers",
        "fuel_records",
        "invoices",
        "maintenance_records",
        "payments",
        "subscriptions",
        "trips",
        "users",
        "vehicle_locations",
        "vehicles",
    }
    assert any(
        relationship.references_table == "customers"
        for relationship in tables["vehicles"].relationships
    )
    assert any(
        relationship.references_table == "invoices"
        for relationship in tables["payments"].relationships
    )


def test_foreign_keys_are_enforced(database_session: Session) -> None:
    database_session.add(
        Customer(
            id=1,
            name="Test Contact",
            email="test@example.com",
            company_name="Test Fleet",
            city="Austin",
            state="Texas",
            country="United States",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            status="active",
        )
    )
    database_session.commit()

    database_session.add(
        Vehicle(
            id=1,
            customer_id=999,
            registration_number="INVALID-1",
            vehicle_type="van",
            manufacturer="Ford",
            model="Transit",
            fuel_type="diesel",
            city="Austin",
            state="Texas",
            status="active",
            purchase_date=date(2024, 1, 1),
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
    )

    with pytest.raises(IntegrityError):
        database_session.commit()

    database_session.rollback()
    assert database_session.scalar(select(Customer.id)) == 1
