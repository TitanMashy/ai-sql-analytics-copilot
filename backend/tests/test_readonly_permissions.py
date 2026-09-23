import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings


@pytest.mark.integration
def test_analytics_role_can_read_but_cannot_modify() -> None:
    settings = get_settings()
    if not settings.analytics_database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL analytics credentials are not configured")

    engine = create_engine(settings.analytics_database_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM customers")).scalar_one() >= 0
        for statement in (
            "INSERT INTO customers (id) VALUES (999999)",
            "UPDATE customers SET name = 'permission probe' WHERE id = 1",
            "DELETE FROM customers WHERE id = 1",
            "DROP TABLE customers",
        ):
            with pytest.raises(SQLAlchemyError):
                connection.execute(text(statement))
            connection.rollback()
