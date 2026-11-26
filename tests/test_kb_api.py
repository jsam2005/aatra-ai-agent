from tests.conftest import ADMIN

ARTICLE = {
    "title": "Webhooks",
    "content": "Nimbus can send webhooks for task events. Configure them under Settings > Integrations > Webhooks.",
    "category": "Integrations",
    "tags": ["webhooks", "api"],
}


def test_crud_lifecycle(client):
    created = client.post("/api/v1/kb/articles", json=ARTICLE, headers=ADMIN)
    assert created.status_code == 201
    art = created.json()
    assert art["category"] == "integrations"  # normalised
    assert art["tags"] == ["webhooks", "api"]

    got = client.get(f"/api/v1/kb/articles/{art['id']}").json()
    assert got["title"] == "Webhooks"

    patched = client.patch(f"/api/v1/kb/articles/{art['id']}", json={"title": "Outgoing webhooks"}, headers=ADMIN)
    assert patched.status_code == 200
    assert patched.json()["title"] == "Outgoing webhooks"
    assert patched.json()["content"] == ARTICLE["content"]  # untouched fields kept

    listed = client.get("/api/v1/kb/articles", params={"category": "integrations"}).json()
    assert listed["total"] == 1

    assert client.delete(f"/api/v1/kb/articles/{art['id']}", headers=ADMIN).status_code == 204
    missing = client.get(f"/api/v1/kb/articles/{art['id']}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_search_index_follows_writes(client):
    art = client.post("/api/v1/kb/articles", json=ARTICLE, headers=ADMIN).json()
    hits = client.get("/api/v1/kb/articles/search", params={"q": "webhooks"}).json()
    assert hits[0]["id"] == art["id"]

    # unpublishing hides it from the agent's search
    client.patch(f"/api/v1/kb/articles/{art['id']}", json={"is_published": False}, headers=ADMIN)
    hits = client.get("/api/v1/kb/articles/search", params={"q": "webhooks"}).json()
    assert all(h["id"] != art["id"] for h in hits)

    # content updates are re-indexed by the FTS trigger
    client.patch(f"/api/v1/kb/articles/{art['id']}", json={"is_published": True, "content": "Zapier integration guide and setup steps."}, headers=ADMIN)
    assert client.get("/api/v1/kb/articles/search", params={"q": "zapier"}).json()[0]["id"] == art["id"]

    client.delete(f"/api/v1/kb/articles/{art['id']}", headers=ADMIN)
    assert client.get("/api/v1/kb/articles/search", params={"q": "zapier"}).json() == []


def test_search_is_injection_safe(client):
    # FTS5 operators and quotes in user input must not raise syntax errors
    for q in ['refund" OR content:*', "NEAR(refund policy)", "refund AND -", '"""']:
        assert client.get("/api/v1/kb/articles/search", params={"q": q}).status_code == 200


def test_validation_error_shape(client):
    r = client.post("/api/v1/kb/articles", json={"title": "x", "content": "short", "category": "b"}, headers=ADMIN)
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_failed"
    assert {tuple(e["loc"])[-1] for e in body["details"]["errors"]} >= {"title", "content", "category"}
