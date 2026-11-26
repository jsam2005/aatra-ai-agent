# Database schema

SQLite by default (`DATABASE_URL` can point at Postgres; the models use only portable types).
Tables are created on startup by `init_db()` (`app/db.py`); enums are stored as strings and
timestamps in UTC. Connection settings: `PRAGMA foreign_keys=ON`, WAL journal mode, 15 s busy
timeout. After a schema change, run `make reset` locally (no migrations; Alembic in production).

There are two groups of tables:

* **Support domain** (owned by this service): knowledge base, conversations, messages, the agent's
  audit trail, pending actions, feedback.
* **Mock SaaS backend** (would be other systems in production: identity provider, billing
  platform, helpdesk). They share the database only for convenience; the agent reaches them
  exclusively through the interfaces in `app/backend/interfaces.py`.

```mermaid
erDiagram
    users ||--o{ conversations : "has"
    users ||--o{ subscriptions : "has"
    users ||--o{ payment_methods : "has"
    users ||--o{ invoices : "billed"
    users ||--o{ password_reset_requests : "requested"
    users ||--o{ support_tickets : "opened"
    users ||--o{ pending_actions : "owns"
    users ||--o{ feedback : "gives"

    conversations ||--o{ messages : "contains"
    conversations ||--o{ pending_actions : "proposed in"
    conversations |o--o{ support_tickets : "escalated from"
    messages ||--o{ tool_invocations : "produced"
    messages ||--o| feedback : "rated by"
    messages |o--o{ pending_actions : "proposed by"

    plans ||--o{ subscriptions : "priced by"
    subscriptions ||--o{ invoices : "generates"
    invoices ||--o{ payment_attempts : "charged by"
    payment_methods |o--o{ payment_attempts : "used in"

    kb_articles ||--|| kb_articles_fts : "indexed by (triggers)"

    kb_articles {
        int id PK
        string title
        text content
        string category "indexed"
        string tags "space-separated"
        bool is_published "indexed"
        datetime created_at
        datetime updated_at
    }
    kb_articles_fts {
        virtual fts5 "title, content, tags; porter stemming; BM25"
    }
    conversations {
        int id PK
        int user_id FK
        string title "first message, 80 chars"
        datetime created_at
        datetime updated_at
    }
    messages {
        int id PK
        int conversation_id FK
        enum role "user | assistant"
        text content
        string request_id "indexed; pairs a user turn with its reply"
        enum route "assistant only; derived from tools used"
        json citations "KB article ids actually retrieved"
        string provider "gemini | offline | system"
        string model
        bool degraded "finished by fallback provider"
        string fallback_reason "rate_limited | server_error | ..."
        int model_calls
        int latency_ms
        int input_tokens "NULL = not reported"
        int output_tokens "NULL = not reported"
        datetime created_at
    }
    tool_invocations {
        int id PK
        int message_id FK
        string tool_name
        json arguments
        json result
        enum status "success | error | pending_confirmation"
        int duration_ms
        datetime created_at
    }
    pending_actions {
        int id PK
        int user_id FK
        int conversation_id FK
        int message_id FK
        string tool_name
        json arguments
        string summary "shown on Confirm button"
        enum status "pending | confirmed | failed | cancelled | expired"
        json result
        datetime created_at
        datetime expires_at
        datetime resolved_at
    }
    feedback {
        int id PK
        int message_id FK "UNIQUE"
        int user_id FK
        enum rating "up | down"
        text comment
        datetime created_at
        datetime updated_at
    }
    users {
        int id PK
        string email UK
        string name
        datetime created_at
    }
    plans {
        int id PK
        string code UK
        string name
        int price_cents
        string currency
        string interval
        int seats
    }
    subscriptions {
        int id PK
        int user_id FK
        int plan_id FK
        enum status "trialing | active | past_due | cancelled"
        date current_period_start
        date current_period_end
        bool cancel_at_period_end
        datetime created_at
    }
    payment_methods {
        int id PK
        int user_id FK
        string brand
        string last4
        int exp_month
        int exp_year
        bool is_default
    }
    invoices {
        int id PK
        int user_id FK
        int subscription_id FK
        string number UK
        int amount_cents
        string currency
        enum status "paid | payment_due | void"
        date issued_on
        datetime paid_at
    }
    payment_attempts {
        int id PK
        int invoice_id FK
        int payment_method_id FK
        enum status "succeeded | failed"
        enum decline_code "card_expired | insufficient_funds | card_declined | processing_error"
        datetime attempted_at
    }
    password_reset_requests {
        int id PK
        int user_id FK
        string sent_to
        datetime created_at
        datetime expires_at
    }
    support_tickets {
        int id PK
        int user_id FK
        int conversation_id FK
        string subject
        text summary
        enum priority "low | normal | high"
        enum status "open | resolved"
        datetime created_at
    }
```

## Constraints and indexes

| Table | Constraint / index | Purpose |
|---|---|---|
| `users` | `UNIQUE(email)` | one account per email |
| `plans` | `UNIQUE(code)` | stable plan identifiers |
| `invoices` | `UNIQUE(number)`, index on `user_id`, `subscription_id` | invoice lookup by customer-visible number |
| `feedback` | `UNIQUE(message_id)` | one rating per answer; `PUT` replaces it |
| `kb_articles` | index on `category`, `is_published` | admin filtering, published-only search |
| `messages` | index on `conversation_id`, `route`, `request_id` | history, analytics, trace lookup |
| `tool_invocations` | index on `message_id`, `tool_name` | trace and per-tool analytics |
| `pending_actions` | index on `user_id`, `conversation_id`, `status` | ownership checks, open actions |
| all `*_id` foreign keys | enforced (`foreign_keys=ON`) | ownership chain user → conversation → message |

Cascades: deleting a conversation removes its messages (ORM cascade), their tool invocations and
feedback, and its pending actions (`ON DELETE CASCADE`). Support tickets survive with
`conversation_id` set to NULL, because the human follow-up must not disappear (tested).

## Transaction design

- **One session per HTTP request** (`app/api/deps.py`): committed on success, rolled back on error.
- **Chat turns commit in steps** (`ChatService.send_message`): the user message is committed before
  the first Gemini call, and the agent commits after every tool round (`checkpoint`). SQLite has a
  single writer, and a model call takes seconds, so no write lock is held while waiting on Gemini.
  Side effects of completed tools are durable even if a later model call fails.
- **Atomic statements where races matter:**
  - confirmation claim: `UPDATE pending_actions SET status='confirmed' WHERE id=? AND user_id=? AND status='pending' AND expires_at>now` (rowcount decides the winner);
  - password-reset cooldown: `INSERT … SELECT … WHERE NOT EXISTS (reset in last 10 min)`.

## Modelling notes

* **Money in integer cents** plus an ISO currency code, never floats.
* **`messages` stores how each answer was made** (request id, route, citations, provider, model,
  model calls, tokens, latency, degraded flag and reason). Together with `tool_invocations` this
  is the audit trail: for any answer you can see which tools ran, with which arguments, and what
  they returned. Missing token counts are stored as NULL, never as 0.
* **`feedback.message_id` is UNIQUE**: one rating per answer; re-rating replaces it (PUT is
  idempotent). Feedback joins to `messages.route`, so satisfaction can be broken down by how
  the agent answered.
* **`pending_actions`** persist the exact arguments the user approves; confirmation replays those
  arguments, not a new model output. Status changes are single-use, so a double click cannot
  double-charge.
* **Invoice → payment_attempts** models dunning: the number of failed attempts drives
  `retries_remaining`, and the decline code drives the recommended next step.
* **FTS index sync** happens in SQLite triggers (`AFTER INSERT/UPDATE/DELETE ON kb_articles`), so
  every write path, ORM or raw SQL, keeps search consistent.
* **Deletion:** deleting a conversation cascades to messages, tool invocations, feedback and
  pending actions; tickets keep their row (`conversation_id` set to NULL).
