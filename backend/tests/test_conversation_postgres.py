"""Durable conversations against real PostgreSQL (needs `alembic upgrade head`).

Two store objects over separate sessions stand in for two backend replicas, or one replica before
and after a restart. The tables come from the Alembic migration, so these tests also prove the
migration and the models agree.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.conversation.service import ConversationAccessError
from app.conversation.sql_store import SqlConversationStore
from app.core.config import get_settings
from tests.helpers import require_integration_or_skip

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session_factory():
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        require_integration_or_skip("DATABASE_URL is not a PostgreSQL URL")
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        present = connection.execute(text("SELECT to_regclass('public.conversations')")).scalar()
    if present is None:
        require_integration_or_skip("the conversations table is missing; run alembic upgrade head")
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def owner() -> str:
    return f"integration-{uuid4().hex[:12]}"


def test_a_conversation_survives_a_restart_and_is_visible_to_another_replica(
    session_factory, owner
) -> None:
    conversation_id = f"conv-{uuid4().hex}"
    replica_one = SqlConversationStore(session_factory)
    replica_one.create_session(conversation_id, owner=owner)
    replica_one.add_turn(conversation_id, "user", "Show revenue by customer", owner=owner)
    replica_one.add_turn(
        conversation_id,
        "assistant",
        "Acme led revenue.",
        owner=owner,
        sql="SELECT customer_id, SUM(total_amount) FROM invoices GROUP BY customer_id",
        tables=["invoices"],
    )
    try:
        # A new store object has no memory of the first one: everything comes from PostgreSQL.
        replica_two = SqlConversationStore(session_factory)

        history = replica_two.get_history(conversation_id, owner=owner)
        context = replica_two.build_context(conversation_id, owner=owner)

        assert [turn.role for turn in history] == ["user", "assistant"]
        assert history[1].tables == ("invoices",)
        assert "SQL: SELECT customer_id" in context
    finally:
        replica_one.delete_session(conversation_id, owner=owner)


def test_ownership_is_enforced_across_replicas(session_factory, owner) -> None:
    conversation_id = f"conv-{uuid4().hex}"
    first = SqlConversationStore(session_factory)
    second = SqlConversationStore(session_factory)
    first.add_turn(conversation_id, "user", "private question", owner=owner)
    try:
        assert second.get_session(conversation_id, owner="someone-else") is None
        with pytest.raises(ConversationAccessError):
            second.add_turn(conversation_id, "user", "intruder", owner="someone-else")
        with pytest.raises(ConversationAccessError):
            second.delete_session(conversation_id, owner="someone-else")
        assert second.get_session(conversation_id, owner=owner) is not None
    finally:
        first.delete_session(conversation_id, owner=owner)


def test_turns_are_trimmed_and_deleted_with_the_conversation(session_factory, owner) -> None:
    conversation_id = f"conv-{uuid4().hex}"
    store = SqlConversationStore(session_factory, max_turns=4)
    for index in range(7):
        store.add_turn(conversation_id, "user", f"question {index}", owner=owner)

    assert [turn.content for turn in store.get_history(conversation_id, owner=owner)] == [
        "question 3",
        "question 4",
        "question 5",
        "question 6",
    ]
    assert store.delete_session(conversation_id, owner=owner) is True
    with session_factory() as session:
        remaining = session.execute(
            text("SELECT COUNT(*) FROM conversation_turns WHERE conversation_id = :id"),
            {"id": conversation_id},
        ).scalar_one()
    assert remaining == 0


def test_concurrent_creation_of_the_same_conversation_by_the_same_owner_is_safe(
    session_factory, owner
) -> None:
    conversation_id = f"conv-{uuid4().hex}"
    first = SqlConversationStore(session_factory)
    second = SqlConversationStore(session_factory)
    try:
        assert first.create_session(conversation_id, owner=owner) == conversation_id
        assert second.create_session(conversation_id, owner=owner) == conversation_id
        with pytest.raises(ConversationAccessError):
            second.create_session(conversation_id, owner="someone-else")
    finally:
        first.delete_session(conversation_id, owner=owner)


def test_audit_records_are_written_to_the_database(session_factory) -> None:
    from app.core.audit import AuditEvent, AuditService, DatabaseAuditSink

    request_id = f"req-{uuid4().hex[:12]}"
    AuditService([DatabaseAuditSink(session_factory)]).record(
        AuditEvent(
            event="ask",
            outcome="success",
            request_id=request_id,
            principal="integration",
            sql_hash="0" * 64,
            tables=("vehicles",),
            row_count=3,
            duration_ms=12.5,
        )
    )

    with session_factory() as session:
        row = session.execute(
            text("SELECT event, outcome, tables, row_count FROM audit_log WHERE request_id = :id"),
            {"id": request_id},
        ).one()
        session.execute(text("DELETE FROM audit_log WHERE request_id = :id"), {"id": request_id})
        session.commit()
    assert tuple(row) == ("ask", "success", "vehicles", 3)


def test_the_analytics_role_cannot_read_operational_tables(session_factory) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    settings = get_settings()
    engine = create_engine(settings.analytics_database_url)
    try:
        for table in ("conversations", "conversation_turns", "audit_log"):
            with engine.connect() as connection:
                with pytest.raises(SQLAlchemyError):
                    connection.execute(text(f"SELECT 1 FROM public.{table} LIMIT 1"))
    finally:
        engine.dispose()
