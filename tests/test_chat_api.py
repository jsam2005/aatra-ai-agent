"""End-to-end API tests with the offline provider (deterministic, no network)."""

from datetime import timedelta

from app.db import utcnow
from app.models import Invoice, PendingAction, Subscription
from tests.conftest import ADMIN, as_user


def chat(client, user_id, message, conversation_id=None):
    r = client.post("/api/v1/chat", json={"message": message, "conversation_id": conversation_id}, headers=as_user(user_id))
    assert r.status_code == 200, r.text
    return r.json()


def test_kb_question_is_answered_from_kb_with_citation(client):
    body = chat(client, 1, "What is your refund policy?")
    reply = body["reply"]
    assert reply["route"] == "knowledge_base"
    assert reply["citations"][0]["title"] == "Refund policy"
    assert "14 days" in reply["content"]
    assert "[KB-" not in reply["content"]  # markers become structured citations


def test_subscription_question_reads_backend(client):
    reply = chat(client, 1, "What is my current subscription?")["reply"]
    assert reply["route"] == "backend_read"
    assert "Pro" in reply["content"]
    assert [t["tool_name"] for t in reply["tool_calls"]] == ["get_subscription"]


def test_password_reset_executes_action_once(client):
    first = chat(client, 1, "Reset my password")["reply"]
    assert first["route"] == "backend_action"
    assert "a***@example.com" in first["content"]
    again = chat(client, 1, "reset my password again please")["reply"]
    assert "already sent" in again["content"]  # cooldown: no second email


def test_payment_failed_expired_card_guides_card_update(client):
    reply = chat(client, 2, "My payment failed")["reply"]
    assert reply["route"] == "backend_read"
    assert "expired" in reply["content"]
    assert reply["citations"][0]["title"] == "Update your payment method"


def test_payment_failed_retry_requires_confirmation_then_executes(client, settings):
    body = chat(client, 3, "My payment failed")
    assert body["reply"]["route"] == "pending_confirmation"
    [action] = body["pending_actions"]
    assert "199.00 USD" in action["summary"]

    # nothing has been charged yet
    conv = client.get(f"/api/v1/conversations/{body['conversation_id']}", headers=as_user(3)).json()
    assert conv["pending_actions"][0]["id"] == action["id"]

    # another user cannot confirm it
    assert client.post(f"/api/v1/actions/{action['id']}/confirm", headers=as_user(1)).status_code == 404

    done = client.post(f"/api/v1/actions/{action['id']}/confirm", headers=as_user(3))
    assert done.status_code == 200
    assert done.json()["action"]["status"] == "confirmed"
    assert "Payment successful" in done.json()["message"]["content"]

    # confirming twice is rejected (no double charge)
    again = client.post(f"/api/v1/actions/{action['id']}/confirm", headers=as_user(3))
    assert again.status_code == 409

    # the outcome is in the conversation history, and the account is healthy again
    sub = chat(client, 3, "What is my current subscription?", body["conversation_id"])["reply"]
    assert "'active'" in sub["content"]
    history = client.get(f"/api/v1/conversations/{body['conversation_id']}", headers=as_user(3)).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "assistant", "user", "assistant"]


def test_cancelled_action_is_never_executed(client, settings):
    body = chat(client, 3, "my card payment was declined")
    action_id = body["pending_actions"][0]["id"]
    r = client.post(f"/api/v1/actions/{action_id}/cancel", headers=as_user(3))
    assert r.json()["action"]["status"] == "cancelled"
    assert client.post(f"/api/v1/actions/{action_id}/confirm", headers=as_user(3)).status_code == 409

    with client.app.state.container.session_factory() as s:
        assert s.query(Invoice).filter_by(number="INV-3003").one().status.value == "payment_due"


def test_expired_action_cannot_be_confirmed(client):
    body = chat(client, 3, "My payment failed")
    action_id = body["pending_actions"][0]["id"]
    with client.app.state.container.session_factory.begin() as s:
        s.get(PendingAction, action_id).expires_at = utcnow() - timedelta(minutes=1)
    r = client.post(f"/api/v1/actions/{action_id}/confirm", headers=as_user(3))
    assert r.status_code == 409
    assert r.json()["error"]["details"]["status"] == "expired"


def test_payment_failed_retries_exhausted_escalates(client):
    reply = chat(client, 4, "My payment failed")["reply"]
    assert reply["route"] == "escalation"
    assert "SUP-" in reply["content"]


def test_healthy_account_payment_question(client):
    reply = chat(client, 1, "my payment failed?")["reply"]
    assert "no unpaid invoices" in reply["content"]


def test_conversation_history_and_isolation(client):
    first = chat(client, 1, "hello")
    cid = first["conversation_id"]
    chat(client, 1, "What is your refund policy?", cid)

    conv = client.get(f"/api/v1/conversations/{cid}", headers=as_user(1)).json()
    assert len(conv["messages"]) == 4
    assert conv["title"] == "hello"

    listed = client.get("/api/v1/conversations", headers=as_user(1)).json()
    assert listed["total"] == 1

    # other users see "not found", never someone else's data
    assert client.get(f"/api/v1/conversations/{cid}", headers=as_user(2)).status_code == 404
    r = client.post("/api/v1/chat", json={"message": "hi", "conversation_id": cid}, headers=as_user(2))
    assert r.status_code == 404

    assert client.delete(f"/api/v1/conversations/{cid}", headers=as_user(1)).status_code == 204
    assert client.get(f"/api/v1/conversations/{cid}", headers=as_user(1)).status_code == 404


def test_deleting_a_conversation_cleans_up_but_keeps_tickets(client):
    from app.models import SupportTicket

    retry = chat(client, 3, "My payment failed")
    escalated = chat(client, 4, "My payment failed")
    client.put(f"/api/v1/messages/{retry['reply']['id']}/feedback", json={"rating": "up"}, headers=as_user(3))

    assert client.delete(f"/api/v1/conversations/{retry['conversation_id']}", headers=as_user(3)).status_code == 204
    assert client.delete(f"/api/v1/conversations/{escalated['conversation_id']}", headers=as_user(4)).status_code == 204

    with client.app.state.container.session_factory() as s:
        assert s.query(PendingAction).count() == 0
        ticket = s.query(SupportTicket).one()  # the human follow-up must survive
        assert ticket.conversation_id is None
    assert client.get("/api/v1/feedback/summary", headers=ADMIN).json()["total"] == 0


def test_auth_required(client):
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/api/v1/chat", json={"message": "hi"}, headers=as_user(999)).status_code == 401


def test_health(client):
    assert client.get("/health").json()["llm_provider"] == "offline"


def test_subscription_reactivated_after_successful_retry(client):
    body = chat(client, 3, "My payment failed")
    client.post(f"/api/v1/actions/{body['pending_actions'][0]['id']}/confirm", headers=as_user(3))
    with client.app.state.container.session_factory() as s:
        assert s.query(Subscription).filter_by(user_id=3).one().status.value == "active"
