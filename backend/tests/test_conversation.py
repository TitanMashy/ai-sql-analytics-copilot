from app.conversation.service import ConversationMemory, ConversationTurn


def test_conversation_memory_keeps_latest_context_within_budget() -> None:
    store = ConversationMemory(max_turns=4, max_chars=400)
    for index in range(1, 8):
        store.add_turn(
            "demo",
            "user",
            f"What was revenue in month {index}?",
        )
        store.add_turn(
            "demo",
            "assistant",
            f"Revenue for month {index} was ${index * 1000}.",
        )

    context = store.build_context("demo")

    assert "month 7" in context.lower()
    assert len(context) <= 400
    assert "month 1" not in context.lower()


def test_turns_are_normalized_and_usable_for_follow_up_questions() -> None:
    store = ConversationMemory(max_turns=5, max_chars=500)
    store.add_turn("session-1", "user", "Show monthly revenue for the last 12 months.")
    store.add_turn("session-1", "assistant", "The total was $120k.")

    history = store.get_history("session-1")
    assert history[0] == ConversationTurn(
        role="user",
        content="Show monthly revenue for the last 12 months.",
    )
    assert history[1] == ConversationTurn(
        role="assistant",
        content="The total was $120k.",
    )
    assert "monthly revenue" in store.build_context("session-1").lower()
