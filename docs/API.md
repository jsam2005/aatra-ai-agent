# API reference

Base URL `http://localhost:8000`. Interactive docs at **`/docs`** (Swagger UI) and `/redoc`. The
OpenAPI spec is generated from the FastAPI app (`make openapi`) and committed as
[`openapi.json`](openapi.json).

## Authentication (demo only)

| Header | Used by | Value |
|---|---|---|
| `X-User-Id` | chat, conversations, actions, rating a message | seeded customer `1`-`4` |
| `X-Admin-Key` | KB create/update/delete, KB drafts, feedback list and summary, analytics overview | `ADMIN_API_KEY` (default `nimbus-admin-demo`) |

These headers stand in for a real identity provider. They are **not** production security. The
backend still enforces everything else: ownership on every lookup (another user's resource
returns 404), and tools that can only act on the authenticated user.

| Customer | State | Try |
|---|---|---|
| 1 Asha Raman | Pro, all paid | KB questions, subscription, password reset |
| 2 Ben Carter | Starter, past due, card **expired** | "My payment failed" → update card |
| 3 Chen Wei | Business, past due, **insufficient funds**, valid card | "My payment failed" → confirm retry |
| 4 Diana Okafor | Pro, past due, **3 failed retries** | "My payment failed" → ticket |

## Errors

Every error has the same shape. Unexpected errors never include internal details.

```json
{ "error": { "code": "not_found", "message": "Conversation 42 not found", "details": {} } }
```

| HTTP | code | when |
|---|---|---|
| 401 | `unauthorized` | missing/unknown `X-User-Id`, or missing `X-Admin-Key` |
| 403 | `forbidden` | wrong `X-Admin-Key` |
| 404 | `not_found` | missing **or owned by another user** |
| 409 | `conflict` | confirming/cancelling an action that is no longer pending (`details.status`: confirmed, failed, cancelled, expired) |
| 422 | `validation_failed` | bad body, path or query (`details.errors[]`), or rating a user message |
| 503 | `llm_unavailable` | Gemini failed and `AI_DEGRADE_TO_OFFLINE=false` (`details.reason`) |
| 500 | `internal_error` | unexpected; logged server-side only |

---

## Chat

### `POST /api/v1/chat`

Send a message. Omit `conversation_id` to start a conversation. `message` must be 1-4000 characters.

```bash
curl -s localhost:8000/api/v1/chat -H 'X-User-Id: 3' -H 'Content-Type: application/json' \
  -d '{"message": "My payment failed"}'
```

Response (shape is exact; values are from a live Gemini run and the wording varies):

```json
{
  "conversation_id": 1,
  "user_message": { "id": 1, "role": "user", "content": "My payment failed", "request_id": "9f1c…", "...": "..." },
  "reply": {
    "id": 2,
    "role": "assistant",
    "content": "Your payment for invoice INV-3003 of 199.00 USD failed because your bank declined the charge for insufficient funds. …",
    "route": "pending_confirmation",
    "citations": [],
    "tool_calls": [
      { "tool_name": "get_payment_issue", "status": "success", "arguments": {}, "duration_ms": 3 },
      { "tool_name": "retry_payment", "status": "pending_confirmation", "arguments": { "invoice_number": "INV-3003" }, "duration_ms": 2 }
    ],
    "request_id": "9f1c…",
    "provider": "gemini",
    "model": "gemini-3.5-flash-lite",
    "degraded": false,
    "fallback_reason": null,
    "latency_ms": 6120,
    "model_calls": 3,
    "input_tokens": 4400,
    "output_tokens": 98,
    "actions": [
      { "id": 1, "tool_name": "retry_payment", "summary": "Charge 199.00 USD for invoice INV-3003 to Visa ending 4243",
        "status": "pending", "expires_at": "2026-11-26T09:15:00", "result": null }
    ],
    "feedback": null
  },
  "pending_actions": [ { "id": 1, "status": "pending", "...": "..." } ]
}
```

| Field | Meaning |
|---|---|
| `route` | how the answer was produced, derived from the tools that ran: `knowledge_base`, `backend_read`, `backend_action`, `pending_confirmation`, `escalation`, `direct`, `error` |
| `citations` | KB articles the answer used (only ones search actually returned): `[{"id": 1, "title": "Refund policy"}]` |
| `tool_calls` | execution trace: tool, arguments, status, duration |
| `provider` / `model` | `gemini`, `offline`, or `system` (action outcomes) |
| `degraded` / `fallback_reason` | Gemini failed mid-turn and the offline engine finished it (`rate_limited`, `server_error`, `unreachable`, `malformed`, `empty`, …) |
| `input_tokens` / `output_tokens` | provider-reported; `null` = not reported (offline) |
| `actions` | confirmation-gated actions this answer proposed, with their **current** status |
| `cards` | structured views of successful tool results, **whitelisted fields only**: `subscription`, `invoices`, `payment_issue` (or `{"none": true}`), `password_reset`, `ticket`. Example: `{"type": "password_reset", "data": {"sent_to": "a***@example.com", "link_valid_for": "1 hour", "already_sent_recently": false, "simulated": true}}` |

### Conversations

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/conversations` | Create an empty conversation → `201` |
| `GET` | `/api/v1/conversations?limit=&offset=` | My conversations, most recent first (`limit` 1-100) |
| `GET` | `/api/v1/conversations/{id}` | Full history (messages with trace, citations, actions, feedback) + open actions |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a message in an existing conversation: `{"message": "..."}` |
| `DELETE` | `/api/v1/conversations/{id}` | Delete with messages, tool logs, feedback, pending actions (tickets kept) → `204` |

### Pending actions (human in the loop)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/actions/{id}` | Current status |
| `POST` | `/api/v1/actions/{id}/confirm` | Execute it. No request body: amount and target are the stored ones. Atomic and single-use; eligibility is re-checked. |
| `POST` | `/api/v1/actions/{id}/cancel` | Cancel it |

```bash
curl -s -X POST localhost:8000/api/v1/actions/1/confirm -H 'X-User-Id: 3'
```

```json
{
  "action": { "id": 1, "status": "confirmed",
              "result": { "ok": true, "invoice_number": "INV-3003", "succeeded": true, "decline_code": null, "amount": "199.00 USD" }, "...": "..." },
  "message": { "id": 3, "role": "assistant", "route": "backend_action", "provider": "system",
               "content": "Payment successful: Charged 199.00 USD to Visa ending 4243. Your subscription is active again.", "...": "..." }
}
```

A second confirm, a confirm after cancel, or a confirm after 15 minutes returns `409`.
If eligibility changed (e.g. the card expired), the action ends as `failed` and nothing is charged.

---

## Knowledge base

Reads are public and return **published** articles only (drafts need `X-Admin-Key`). Writes
require `X-Admin-Key`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/kb/articles?category=&published=&q=&limit=&offset=` | List and filter, paginated |
| `GET` | `/api/v1/kb/articles/search?q=&limit=` | Ranked BM25 search: exactly what the agent's tool sees |
| `GET` | `/api/v1/kb/articles/{id}` | One article |
| `POST` | `/api/v1/kb/articles` | Create (admin) → `201` |
| `PATCH` | `/api/v1/kb/articles/{id}` | Partial update (admin); the search index updates via trigger |
| `DELETE` | `/api/v1/kb/articles/{id}` | Delete (admin) → `204` |

```bash
curl -s localhost:8000/api/v1/kb/articles -H 'X-Admin-Key: nimbus-admin-demo' \
  -H 'Content-Type: application/json' -d '{
    "title": "Webhooks",
    "content": "Configure webhooks under Settings > Integrations > Webhooks.",
    "category": "integrations",
    "tags": ["webhooks", "api"],
    "is_published": true
  }'
```

Body limits: `title` 3-200, `content` 10-20000, `category` 2-50 (lower-cased), `tags` ≤ 20.

---

## Feedback

| Method | Path | Auth | Description |
|---|---|---|---|
| `PUT` | `/api/v1/messages/{id}/feedback` | user | Rate my assistant message: `{"rating": "up"\|"down", "comment": "…"}`. `201` first time, `200` when replacing. |
| `GET` | `/api/v1/messages/{id}/feedback` | user | My rating of that message |
| `GET` | `/api/v1/feedback?rating=&route=&limit=&offset=` | admin | Ratings with route and message excerpt |
| `GET` | `/api/v1/feedback/summary` | admin | Totals, satisfaction, per route and per tool |

```json
{ "total": 2, "up": 1, "down": 1, "satisfaction": 0.5,
  "by_route": [ { "route": "knowledge_base", "up": 1, "down": 0, "satisfaction": 1.0 }, { "route": "backend_read", "up": 0, "down": 1, "satisfaction": 0.0 } ],
  "by_tool":  [ { "tool_name": "get_subscription", "up": 0, "down": 1, "satisfaction": 0.0 }, { "tool_name": "search_knowledge_base", "up": 1, "down": 0, "satisfaction": 1.0 } ] }
```

---

## Analytics (admin)

### `GET /api/v1/analytics/overview`

Aggregates over stored data only (no estimates):

```json
{
  "conversations": 2, "responses": 2, "degraded_responses": 0, "avg_latency_ms": 4,
  "responses_by_route": [ { "route": "knowledge_base", "count": 1 }, { "route": "pending_confirmation", "count": 1 } ],
  "tools": [ { "tool_name": "retry_payment", "calls": 1, "succeeded": 0, "errors": 0, "awaiting_confirmation": 1, "avg_duration_ms": 2.0 } ],
  "feedback_by_day": [ { "date": "2026-11-26", "up": 1, "down": 0 } ]
}
```

`feedback_by_day` always covers the last 14 days, zero-filled. `responses` excludes system
messages created by confirmations.

---

## Health

`GET /health` →
`{"status": "ok", "llm_provider": "gemini", "llm_model": "gemini-3.5-flash-lite", "fallback_provider": "offline"}`

`GET /` serves the built React UI (or redirects to `/docs` if the UI hasn't been built).
