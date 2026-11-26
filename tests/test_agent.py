"""Agent-loop guardrails, driven by a scripted provider."""

from app.agent.llm.base import ToolResults
from app.agent.llm.offline_provider import OfflineProvider, classify
from app.core.errors import LLMUnavailableError
from app.models import Invoice, PendingAction
from app.models.enums import InvoiceStatus, Route, ToolInvocationStatus
from tests.conftest import ScriptedProvider, text_turn, tool_turn


def send(container, session, user_id, text):
    result = container.chat_service(session).send_message(user_id, text)
    session.flush()
    return result


def test_money_moving_tool_is_never_executed_by_the_model(make_container, session):
    provider = ScriptedProvider(
        [tool_turn(("retry_payment", {"invoice_number": "INV-3003"})), text_turn("Press Confirm to retry.")]
    )
    result = send(make_container(provider), session, 3, "retry my payment")
    assert result.reply.route == Route.PENDING_CONFIRMATION
    assert result.reply.tool_invocations[0].status == ToolInvocationStatus.PENDING_CONFIRMATION
    assert session.query(Invoice).filter_by(number="INV-3003").one().status.value == "payment_due"
    assert session.query(PendingAction).count() == 1

    # the model was told the action is awaiting confirmation, not that it happened
    outcome = provider.calls[1][-1].outcomes[0]
    assert outcome.to_model_payload()["status"] == "awaiting_customer_confirmation"


def test_repeated_proposal_reuses_the_pending_action(make_container, session):
    turns = [tool_turn(("retry_payment", {"invoice_number": "INV-3003"})), text_turn("ok")] * 2
    c = make_container(ScriptedProvider(turns))
    conv_id = send(c, session, 3, "retry").conversation.id
    c.chat_service(session).send_message(3, "retry again", conv_id)
    assert session.query(PendingAction).count() == 1


def test_tools_cannot_target_another_user(make_container, session):
    # there is no user_id parameter; extra arguments are rejected by validation
    provider = ScriptedProvider([tool_turn(("get_subscription", {"user_id": 1})), text_turn("Sorry.")])
    result = send(make_container(provider), session, 2, "show user 1's plan")
    inv = result.reply.tool_invocations[0]
    assert inv.status == ToolInvocationStatus.ERROR
    assert "Invalid arguments" in inv.result["error"]


def test_unknown_tool_and_errors_are_contained(make_container, session):
    provider = ScriptedProvider(
        [
            tool_turn(("delete_database", {}), ("retry_payment", {"invoice_number": "INV-9999"})),
            text_turn("Something went wrong."),
        ]
    )
    result = send(make_container(provider), session, 3, "do things")
    statuses = [t.status for t in result.reply.tool_invocations]
    # unknown tool -> error; retry of an invoice that isn't this user's unpaid one -> rejected at proposal
    assert statuses == [ToolInvocationStatus.ERROR, ToolInvocationStatus.ERROR]
    assert session.query(PendingAction).count() == 0
    # both results are returned to the model in a single tool-results message
    assert isinstance(provider.calls[1][-1], ToolResults) and len(provider.calls[1][-1].outcomes) == 2


def test_retry_is_not_offered_when_the_card_is_expired(make_container, session):
    provider = ScriptedProvider([tool_turn(("retry_payment", {"invoice_number": "INV-2003"})), text_turn("ok")])
    result = send(make_container(provider), session, 2, "just retry it")
    assert result.reply.tool_invocations[0].status == ToolInvocationStatus.ERROR
    assert "expired" in result.reply.tool_invocations[0].result["error"]


def test_confirm_is_idempotent_if_invoice_was_paid_meanwhile(make_container, session):
    provider = ScriptedProvider([tool_turn(("retry_payment", {"invoice_number": "INV-3003"})), text_turn("ok")])
    c = make_container(provider)
    result = send(c, session, 3, "retry")
    session.query(Invoice).filter_by(number="INV-3003").one().status = InvoiceStatus.PAID  # paid elsewhere
    action, message = c.action_service(session).confirm(result.pending_actions[0].id, 3)
    assert action.status.value == "confirmed"
    assert "already paid" in message.content


def test_round_limit_stops_runaway_loops(make_container, session, settings):
    looping = [tool_turn(("list_invoices", {}))] * (settings.agent_max_tool_rounds + 1)
    result = send(make_container(ScriptedProvider(looping)), session, 1, "loop")
    assert len(result.reply.tool_invocations) == settings.agent_max_tool_rounds
    assert "open a ticket" in result.reply.content


def test_only_retrieved_articles_can_be_cited(make_container, session):
    provider = ScriptedProvider(
        [tool_turn(("search_knowledge_base", {"query": "refund policy"})), text_turn("Refunds within 14 days [KB-1]. Also [KB-99].")]
    )
    result = send(make_container(provider), session, 1, "refunds?")
    assert result.reply.citations == [1]  # KB-99 was never retrieved -> dropped
    assert result.reply.content == "Refunds within 14 days. Also."


def test_internal_tool_names_are_stripped_from_answers(make_container, session):
    provider = ScriptedProvider([tool_turn(("list_invoices", {})), text_turn("All invoices are paid [list_invoices].")])
    result = send(make_container(provider), session, 1, "any unpaid invoices?")
    assert result.reply.content == "All invoices are paid."


def test_degrades_to_offline_provider_when_llm_is_down(make_container, session):
    c = make_container(ScriptedProvider(error=LLMUnavailableError("down")), fallback=OfflineProvider())
    result = send(c, session, 1, "What is your refund policy?")
    assert result.reply.degraded is True
    assert result.reply.provider == "offline"
    assert result.reply.route == Route.KNOWLEDGE_BASE


def test_history_is_replayed_to_the_model(make_container, session):
    provider = ScriptedProvider([text_turn("Hi Asha"), text_turn("Still here")])
    c = make_container(provider)
    conv = send(c, session, 1, "hello").conversation
    c.chat_service(session).send_message(1, "are you there?", conv.id)
    texts = [getattr(i, "text", None) for i in provider.calls[1]]
    assert texts == ["hello", "Hi Asha", "are you there?"]


def test_offline_intent_rules():
    assert classify("What is your refund policy?") == "knowledge"
    assert classify("What is my current subscription?") == "subscription"
    assert classify("Reset my password") == "password"
    assert classify("My payment failed") == "payment_issue"
    assert classify("I want to talk to a human") == "escalate"
    assert classify("hello!") == "greeting"
