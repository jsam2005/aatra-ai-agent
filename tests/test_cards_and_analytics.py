"""Structured response cards (whitelisted tool data) and the analytics overview endpoint."""

from tests.conftest import ADMIN, as_user


def _chat(client, user, text):
    r = client.post("/api/v1/chat", json={"message": text}, headers=as_user(user))
    assert r.status_code == 200
    return r.json()


def test_cards_expose_only_whitelisted_fields(client):
    sub = _chat(client, 1, "What is my current subscription?")["reply"]["cards"]
    assert sub[0]["type"] == "subscription"
    assert sub[0]["data"]["plan"] == "Pro"
    assert "plan_code" not in sub[0]["data"] and "ok" not in sub[0]["data"]

    reset = _chat(client, 1, "Reset my password")["reply"]["cards"][0]
    assert reset == {"type": "password_reset", "data": {"sent_to": "a***@example.com", "link_valid_for": "1 hour", "already_sent_recently": False, "simulated": True}}

    issue = _chat(client, 2, "My payment failed")["reply"]["cards"][0]
    assert issue["type"] == "payment_issue"
    assert issue["data"]["recommended_action"] == "update_payment_method"
    assert issue["data"]["payment_method"]["is_expired"] is True
    assert "explanation" not in issue["data"]

    none = _chat(client, 1, "my payment failed?")["reply"]["cards"][0]
    assert none == {"type": "payment_issue", "data": {"none": True}}

    ticket = _chat(client, 4, "My payment failed")["reply"]["cards"]
    assert [c["type"] for c in ticket] == ["payment_issue", "ticket"]
    assert ticket[1]["data"]["ticket_reference"].startswith("SUP-")


def test_cards_survive_reload_from_history(client):
    body = _chat(client, 1, "Show me my invoices")
    conv = client.get(f"/api/v1/conversations/{body['conversation_id']}", headers=as_user(1)).json()
    card = conv["messages"][1]["cards"][0]
    assert card["type"] == "invoices" and card["data"]["invoices"][0]["number"].startswith("INV-1")


def test_analytics_overview_uses_real_data(client):
    assert client.get("/api/v1/analytics/overview").status_code == 401
    empty = client.get("/api/v1/analytics/overview", headers=ADMIN).json()
    assert (empty["conversations"], empty["responses"], empty["tools"]) == (0, 0, [])
    assert len(empty["feedback_by_day"]) == 14 and all(d["up"] == d["down"] == 0 for d in empty["feedback_by_day"])

    kb = _chat(client, 1, "What is your refund policy?")
    _chat(client, 3, "My payment failed")
    client.put(f"/api/v1/messages/{kb['reply']['id']}/feedback", json={"rating": "up"}, headers=as_user(1))

    data = client.get("/api/v1/analytics/overview", headers=ADMIN).json()
    assert (data["conversations"], data["responses"]) == (2, 2)
    assert {r["route"]: r["count"] for r in data["responses_by_route"]} == {"knowledge_base": 1, "pending_confirmation": 1}
    tools = {t["tool_name"]: t for t in data["tools"]}
    assert tools["retry_payment"]["awaiting_confirmation"] == 1 and tools["search_knowledge_base"]["succeeded"] == 1
    assert data["feedback_by_day"][-1]["up"] == 1
