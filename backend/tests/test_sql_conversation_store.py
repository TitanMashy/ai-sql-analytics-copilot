from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.conversation.service import ConversationAccessError, ConversationTurn
from app.conversation.sql_store import SqlConversationStore
from app.db.operational import ConversationRecord, ConversationTurnRecord, OperationalBase


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    OperationalBase.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _store(session_factory, **overrides) -> SqlConversationStore:
    return SqlConversationStore(session_factory, **overrides)


def test_turns_are_durable_and_shared_between_replicas(session_factory) -> None:
    first_replica = _store(session_factory)
    first_replica.create_session("c1", owner="alice")
    first_replica.add_turn("c1", "user", "Show revenue by customer", owner="alice")
    first_replica.add_turn(
        "c1",
        "assistant",
        "Acme led revenue.",
        owner="alice",
        sql="SELECT customer_id, SUM(total_amount) FROM invoices GROUP BY customer_id",
        tables=["invoices"],
    )

    # A second store object over the same database is a restarted or second backend instance.
    second_replica = _store(session_factory)
    history = second_replica.get_history("c1", owner="alice")

    assert [turn.role for turn in history] == ["user", "assistant"]
    assert history[1].sql.startswith("SELECT customer_id")
    assert history[1].tables == ("invoices",)
    assert "SQL: SELECT customer_id" in second_replica.build_context("c1", owner="alice")


def test_ownership_is_enforced_exactly_like_the_in_process_store(session_factory) -> None:
    store = _store(session_factory)
    store.create_session("c1", owner="alice")
    store.add_turn("c1", "user", "alice question", owner="alice")

    assert store.get_session("c1", owner="alice") is not None
    assert store.get_session("c1", owner="bob") is None
    assert store.get_history("c1", owner="bob") == []
    assert store.build_context("c1", owner="bob") == "No prior conversation context."
    with pytest.raises(ConversationAccessError):
        store.add_turn("c1", "user", "bob question", owner="bob")
    with pytest.raises(ConversationAccessError):
        store.assert_access("c1", owner="bob")
    with pytest.raises(ConversationAccessError):
        store.create_session("c1", owner="bob")
    with pytest.raises(ConversationAccessError):
        store.delete_session("c1", owner="bob")
    assert [turn.content for turn in store.get_history("c1", owner="alice")] == ["alice question"]


def test_unknown_conversation_ids_are_created_on_first_turn(session_factory) -> None:
    store = _store(session_factory)

    store.assert_access("never-seen", owner="alice")  # absent is allowed
    store.add_turn("never-seen", "user", "hello", owner="alice")

    assert store.get_session("never-seen", owner="alice") is not None


def test_turns_are_trimmed_to_the_configured_window(session_factory) -> None:
    store = _store(session_factory, max_turns=4)
    for index in range(1, 8):
        store.add_turn("c1", "user", f"question {index}", owner="alice")

    contents = [turn.content for turn in store.get_history("c1", owner="alice")]

    assert contents == ["question 4", "question 5", "question 6", "question 7"]


def test_context_respects_the_character_budget(session_factory) -> None:
    store = _store(session_factory, max_turns=4, max_chars=400)
    for index in range(1, 8):
        store.add_turn("demo", "user", f"What was revenue in month {index}?", owner="o")
        store.add_turn("demo", "assistant", f"Revenue for month {index} was ${index}.", owner="o")

    context = store.build_context("demo", owner="o")

    assert "month 7" in context
    assert len(context) <= 400
    assert "month 1" not in context


def test_per_owner_cap_evicts_that_owners_oldest_conversation(session_factory) -> None:
    store = _store(session_factory, max_sessions_per_owner=2)
    store.create_session("a1", owner="alice")
    store.create_session("a2", owner="alice")
    store.create_session("b1", owner="bob")
    with session_factory() as session, session.begin():
        session.execute(
            update(ConversationRecord)
            .where(ConversationRecord.id == "a1")
            .values(updated_at=datetime.now(UTC) - timedelta(hours=1))
        )

    store.create_session("a3", owner="alice")

    assert store.get_session("a1", owner="alice") is None
    assert store.get_session("a2", owner="alice") is not None
    assert store.get_session("a3", owner="alice") is not None
    assert store.get_session("b1", owner="bob") is not None  # other owners are unaffected


def test_expired_conversations_are_hidden_and_purged(session_factory) -> None:
    store = _store(session_factory, ttl_days=30)
    store.add_turn("old", "user", "an old question", owner="alice")
    store.add_turn("fresh", "user", "a recent question", owner="alice")
    with session_factory() as session, session.begin():
        session.execute(
            update(ConversationRecord)
            .where(ConversationRecord.id == "old")
            .values(updated_at=datetime.now(UTC) - timedelta(days=31))
        )

    assert store.get_session("old", owner="alice") is None
    assert store.count_active() == 1
    assert store.purge_expired() == 1

    with session_factory() as session:
        remaining = set(session.scalars(select(ConversationRecord.id)))
        orphan_turns = session.scalars(
            select(ConversationTurnRecord.id).where(ConversationTurnRecord.conversation_id == "old")
        ).all()
    assert remaining == {"fresh"}
    assert orphan_turns == []
    assert store.purge_expired() == 0  # idempotent


def test_an_expired_id_can_be_reused_by_another_owner(session_factory) -> None:
    store = _store(session_factory, ttl_days=30)
    store.add_turn("shared-id", "user", "alice's old question", owner="alice")
    with session_factory() as session, session.begin():
        session.execute(
            update(ConversationRecord).values(updated_at=datetime.now(UTC) - timedelta(days=40))
        )

    store.add_turn("shared-id", "user", "bob's new question", owner="bob")

    assert [turn.content for turn in store.get_history("shared-id", owner="bob")] == [
        "bob's new question"
    ]
    assert store.get_session("shared-id", owner="alice") is None


def test_delete_removes_the_conversation_and_its_turns(session_factory) -> None:
    store = _store(session_factory)
    store.add_turn("c1", "user", "hello", owner="alice")

    assert store.delete_session("c1", owner="alice") is True
    assert store.delete_session("c1", owner="alice") is False
    assert store.get_session("c1", owner="alice") is None
    with session_factory() as session:
        assert session.scalars(select(ConversationTurnRecord.id)).all() == []


def test_turn_roles_and_content_are_normalized_like_the_in_process_store(session_factory) -> None:
    store = _store(session_factory)

    turn = store.add_turn("c1", "USER", "  padded question  ", owner="alice")

    assert turn == ConversationTurn(role="user", content="padded question")
    assert store.get_history("c1", owner="alice") == [turn]


def test_unauthenticated_development_sessions_share_an_empty_owner(session_factory) -> None:
    store = _store(session_factory)
    store.add_turn("dev", "user", "hello")

    assert store.get_session("dev") is not None
    assert store.get_session("dev", owner="alice") is None
