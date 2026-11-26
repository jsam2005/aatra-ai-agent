from tests.conftest import ADMIN, as_user


def _reply(client, user_id, text):
    return client.post("/api/v1/chat", json={"message": text}, headers=as_user(user_id)).json()


def test_feedback_create_replace_and_summary(client):
    kb = _reply(client, 1, "What is your refund policy?")
    read = _reply(client, 1, "What is my current subscription?")

    r = client.put(f"/api/v1/messages/{kb['reply']['id']}/feedback", json={"rating": "down", "comment": "too long"}, headers=as_user(1))
    assert r.status_code == 201
    r = client.put(f"/api/v1/messages/{kb['reply']['id']}/feedback", json={"rating": "up"}, headers=as_user(1))
    assert r.status_code == 200  # replaced, not duplicated
    assert r.json()["rating"] == "up" and r.json()["comment"] is None
    client.put(f"/api/v1/messages/{read['reply']['id']}/feedback", json={"rating": "down"}, headers=as_user(1))

    summary = client.get("/api/v1/feedback/summary", headers=ADMIN).json()
    assert (summary["total"], summary["up"], summary["down"], summary["satisfaction"]) == (2, 1, 1, 0.5)
    by_route = {s["route"]: s for s in summary["by_route"]}
    assert by_route["knowledge_base"]["up"] == 1
    assert by_route["backend_read"]["down"] == 1

    downs = client.get("/api/v1/feedback", params={"rating": "down"}, headers=ADMIN).json()
    assert downs["total"] == 1 and downs["items"][0]["route"] == "backend_read"

    # feedback is visible on the message in conversation history
    conv = client.get(f"/api/v1/conversations/{kb['conversation_id']}", headers=as_user(1)).json()
    assert conv["messages"][1]["feedback"]["rating"] == "up"


def test_feedback_rules(client):
    body = _reply(client, 1, "hello")
    # only assistant messages can be rated
    r = client.put(f"/api/v1/messages/{body['user_message']['id']}/feedback", json={"rating": "up"}, headers=as_user(1))
    assert r.status_code == 422
    # users can't rate other users' messages
    r = client.put(f"/api/v1/messages/{body['reply']['id']}/feedback", json={"rating": "up"}, headers=as_user(2))
    assert r.status_code == 404
    # invalid rating value
    r = client.put(f"/api/v1/messages/{body['reply']['id']}/feedback", json={"rating": "meh"}, headers=as_user(1))
    assert r.status_code == 422
