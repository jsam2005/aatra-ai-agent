# Design decisions

**Naming:** the product is **Aatra AI Agent**. It is demonstrated for **Nimbus**, a fictional SaaS
client whose help center, customers and billing are seed data. This mirrors how an agency builds
an agent for a client. It is an independent assignment project, not an official Aatra product.

Each record follows the same shape: **context → decision → alternatives → consequences**. File
references point at the code that implements the decision.

The principle behind almost all of them, taken from Aatra's own framing:

> **AI where it pays off, dependable software where it doesn't.** The model decides *what the
> customer needs*. Code decides *what is allowed to happen*.

---

## 1. Overall architecture

A modular monolith: a FastAPI backend with one agent orchestrator, a SQLite database and a React
UI served by the same process.

```
React UI ─▶ FastAPI routers ─▶ services ─▶ SupportAgent ─▶ LLMProvider (Gemini | offline rules)
                                   │             └──────▶ tools ─▶ backend interfaces ─▶ mock services
                                   └─▶ repositories ─▶ SQLite (+ FTS5 index)
```

Layers depend downward only. `app/container.py` is the single place that wires concrete classes,
which is how tests swap Gemini for a scripted fake with one argument. Diagrams:
[docs/architecture.md](docs/architecture.md).

## 2. Why a modular monolith

- **Context:** one small team (me) has 24 hours; the domain has one bounded context (support).
- **Decision:** one deployable with clear internal modules (`api`, `services`, `agent`, `backend`,
  `repositories`).
- **Alternatives:** microservices per capability; a separate agent service. Both add network
  hops, deployment and failure modes with no benefit at this scale.
- **Consequences:** trivial to run (`make run`), one transaction model, one test suite. The
  `backend/` interfaces are the seam where real external services (billing, identity, helpdesk)
  would plug in.

## 3. Why a single agent

- **Context:** the four example requests need at most 2-3 tool calls each.
- **Decision:** one agent with seven narrowly scoped tools, in a bounded loop
  (`SupportAgent.run`, `app/agent/agent.py`).
- **Alternatives:** a router agent plus specialist agents (billing, KB, account). That adds more
  model calls, more latency and more places to lose context, and the "routing" problem is already
  solved by tool selection.
- **Consequences:** one prompt to maintain and one trace per answer. If the tool count grew past
  ~20, I'd consider grouping tools or adding a router, and measure first.

## 4. Why Gemini native function calling, executed manually

- **Context:** the agent must choose between "answer from KB" and "do a backend operation", and
  often chain the two ("my payment failed" = diagnose → maybe retry/escalate/explain).
- **Decision:** declare all seven tools as Gemini `FunctionDeclaration`s with JSON Schemas generated
  from the same Pydantic models that validate arguments. Automatic function calling is **disabled**
  (`AutomaticFunctionCallingConfig(disable=True)`), so Gemini only *proposes* calls. The agent
  loop validates, authorises and executes them, then returns results as `FunctionResponse` parts.
  The model's `Content` is replayed verbatim to keep call ids and thought signatures
  (`app/agent/llm/gemini_provider.py`).
- **Alternatives:** (a) a keyword/LLM classifier routing to fixed handlers: predictable but can't
  chain steps or handle paraphrases; (b) the SDK's automatic function calling: convenient, but the
  SDK would run Python functions directly, bypassing our authorisation, confirmation gate and audit log.
- **Consequences:** genuine model-driven tool selection, with every safety property in code.
  Found during live testing: the Gemini API rejects `role="tool"` for function responses
  (HTTP 400), although the SDK README shows it; results are sent in a `user` turn.

## 5. Which Gemini model, and why Flash

- **Context:** support chat is latency-sensitive and runs on a **free-tier** key; tasks are short
  tool-selection problems, not deep reasoning.
- **Decision:** a Flash-class model, configurable via `GEMINI_MODEL`. What I measured with this key
  on 26 Nov 2026:
  - `gemini-3.8-flash` (preferred): listed as available, but **HTTP 503 "high demand"** on every attempt;
  - `gemini-3.6-flash`: same 503;
  - `gemini-3.7-flash`: worked, but the free tier allows **20 requests per day per model**
    (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), which the live evaluation exhausted
    after one case;
  - `gemini-3.5-flash-lite`: available and used for the live evaluation. **It is the shipped default.**
- **Alternatives:** a Pro-class model: higher cost and latency for no measured benefit here.
- **Consequences:** about 1.3-1.5k input tokens per model call (system prompt + seven tool
  declarations dominate), bounded output (`GEMINI_MAX_OUTPUT_TOKENS=1024`). On the free tier, a
  chat turn costs 2-3 requests, so a 20-requests/day model allows only about 7-10 turns per day.
  Degradation to offline keeps the app usable when the quota runs out, and a paid key removes the
  limit (the account owner's decision; nothing here enables billing).

## 6. Why SQLite

- **Context:** reviewers must be able to run everything with zero infrastructure.
- **Decision:** SQLite with WAL, foreign keys on, a 15 s busy timeout (`app/db.py`). Models use
  only portable types; `DATABASE_URL` can point at Postgres.
- **Alternatives:** Postgres in Docker: more realistic, but a setup step and no benefit for a demo.
- **Consequences:** one writer at a time. I designed around it: the chat service commits *before*
  calling Gemini and after each tool round, so no write lock is held during a multi-second model
  call (§12).

## 7. Why SQLite FTS5 (BM25), not a vector database

- **Context:** 12 short articles; answers must cite the article used.
- **Decision:** an external-content FTS5 index with Porter stemming and title boosting, kept in sync
  by `AFTER INSERT/UPDATE/DELETE` triggers (`app/db.py`, `app/repositories/kb.py`). User text is
  reduced to quoted terms so it can never inject FTS syntax. Search is behind a `Retriever`
  interface (`app/agent/retriever.py`).
- **Alternatives:** embeddings + a vector store: better on synonyms, but adds a model call per
  query, an index to keep in sync, and opaque scores.
- **Consequences:** fast, explainable, zero infrastructure; whenever the search tool ran for an
  answerable KB question in the eval, the right article ranked first. Known weakness: purely lexical. "Do you offer a student discount?"
  matches the refund article on the word *offer*. The model handles that (it says there's no such
  policy), but retrieval itself didn't. Swapping in hybrid retrieval is a one-class change.

## 8. Authorisation enforced in code, not in the prompt

- **Decision:**
  - Tools have **no `user_id` parameter**. They act on `ToolContext.user_id`, which comes from the
    authenticated request. Extra arguments fail validation (`extra="forbid"`).
  - Every lookup includes ownership (`WHERE id = ? AND user_id = ?`), so another user's
    conversation, message or action is a **404**, never a 403 that confirms it exists.
  - Admin operations (KB writes, feedback analytics) need `X-Admin-Key`, compared in constant time.
    Customers only ever see published articles.
- **Why:** a prompt is a suggestion. A capability that doesn't exist can't be talked into.
- **Tests:** `tests/test_security.py`, `tests/test_chat_api.py::test_conversation_history_and_isolation`.
- **Limitation, stated plainly:** `X-User-Id` / `X-Admin-Key` are **demo** authentication. In
  production they would be replaced by verified sessions/JWTs and roles. The rest of the code only
  relies on receiving a trusted user id from `app/api/deps.py`.

## 9. Why payment actions require confirmation, and how it is enforced

- **Decision:** tools declare `requires_confirmation`. When Gemini calls `retry_payment`, the
  agent does **not** run it. It stores a `PendingAction` (exact arguments, human-readable summary,
  15-minute TTL) and tells the model "awaiting confirmation". Only
  `POST /actions/{id}/confirm` executes it, **without any LLM involvement**.
  - **Atomic single use:** a conditional `UPDATE … WHERE status='pending' AND expires_at > now`
    claims the action. Under concurrency exactly one request wins (8 parallel confirms → 1 charge,
    tested).
  - **Re-validated at execution:** eligibility is checked again at confirm time (a card that
    expired in the meantime turns the action into `failed`, no charge).
  - **Untamperable:** confirm takes no body, so the amount and target are the stored ones.
  - **No chat-based approval:** typing "yes" never executes anything (eval case `pay-yes-in-chat`).
- **Proportionate:** `send_password_reset` runs immediately. It can only email the address on
  file, so the worst case is an unwanted email, and it's rate-limited.

## 10. Why an offline fallback exists

- **Decision:** `OfflineProvider` implements the same `LLMProvider` interface with keyword rules
  and templated answers. Three uses:
  1. **No key needed:** reviewers can run every scenario without credentials (`AI_PROVIDER=offline`).
  2. **Degradation:** if Gemini fails *mid-turn* (429, 5xx, timeout, malformed or empty
     response), the **same transcript** continues on the offline provider. Tool results already
     produced are reported, never re-executed. The reply is flagged `degraded` with a reason.
  3. **Deterministic baseline** for tests and the eval.
- **Consequences:** offline answers are plainer and the rules miss some phrasings (measured: 31/35
  eval cases). It's a safety net, not a competitor. `AI_PROVIDER=gemini` without a key fails at
  startup with a clear message instead of silently degrading.

## 11. Conversation context

- **Decision:** the last **20 messages** (text only) are replayed each turn. Within a turn, the
  full model content (function calls, thought signatures) and tool results are replayed.
- **Why:** bounded cost per turn, and no stale account data from old tool results being reused
  (the model re-reads live data when it needs it).
- **Trade-off:** a follow-up may repeat a lookup; very long conversations lose early context.
  Summarising older turns is the next step.

## 12. Idempotency and concurrency

| Risk | Control | Where |
|---|---|---|
| Double charge on double click / concurrent confirms | Atomic conditional UPDATE claim; billing mock never charges a paid invoice | `PendingActionRepository.claim`, `MockBillingService.retry_payment` |
| Duplicate reset emails | Single `INSERT … SELECT … WHERE NOT EXISTS (recent)` statement, 10-minute cooldown | `MockAccountService.send_password_reset` |
| Duplicate tickets | One open ticket per conversation; repeats return the existing reference | `MockTicketService.create_ticket` |
| Duplicate pending actions | Re-proposing the same tool + args in a conversation reuses the live action | `DBActionGate.propose` |
| Repeat work after a provider failure | Fallback continues the same transcript instead of restarting the turn | `SupportAgent.run` |
| Write lock held during model calls | Commit before the model call and after each tool round | `ChatService.send_message`, `checkpoint` |
| Identical reads within a turn | Reused from the first result (saves tokens and I/O) | `SupportAgent._reuse_read` |

## 13. Execution traces

Every assistant message stores: request id, route, cited article ids, provider, model, model-call
count, input/output tokens (**NULL when not reported, never 0**), latency, degraded flag and
reason. `tool_invocations` stores each tool call's name, arguments, status, result and duration.
The UI's **Details** panel (Settings → Evaluation mode) shows the safe subset: no prompts, no model reasoning, no raw tool payloads.
This makes "why did it answer that?" a lookup instead of a guess, and lets feedback be broken
down per route and per tool (`/feedback/summary`).

The **route** label is derived by code from the categories of the tools that actually ran
(`SupportAgent._derive_route`), never self-reported by the model.

## 14. Evaluating AI behaviour

- 35 labelled cases ([evals/cases.json](evals/cases.json)) with expectations written **before**
  running: route, tools, required/forbidden phrases, citations, and **database side effects**
  (payments executed, pending actions, tickets, reset emails).
- Each case runs in a freshly seeded database; multi-turn and setup cases (poisoned article,
  policy edit, billing outage) are supported.
- Fallback is disabled during evaluation, so a provider failure is reported as an error and never
  counted as a Gemini success.
- Results and the method: [docs/evaluation.md](docs/evaluation.md).

## 15. User interface

- **Context:** the UI is how reviewers experience the agent, and it must show the safeguards
  (confirmation, sources) without exposing internals to customers.
- **Decision:**
  - A centralised design-token system (`frontend/src/index.css`: colours, gradients, gloss, depth,
    motion) and a small set of primitives (`components/ui.tsx`). Every page builds from those.
  - **No business logic in the UI.** Cards render only whitelisted fields the backend copies from
    tool results (`app/api/presenters.py::response_cards`). The Confirm button only calls the
    confirm endpoint.
  - Engineering details (route, tools, tokens, engine, fallback) sit behind **Evaluation mode** in
    Settings instead of the default view. The demo admin key moved out of the sidebar into
    Settings as a password field. Hiding it is UX only; the server checks every request.
  - Answers are rendered as Markdown with `react-markdown`. Raw HTML is never rendered, and links
    are restricted to http(s)/mailto. User text is rendered as plain text.
  - The loading state shows a single message ("Understanding your request…"). The API doesn't
    stream, so the client can't know which tool is running, and inventing stages would be dishonest.
  - Analytics come from a new read-only endpoint (`GET /analytics/overview`) plus the existing
    feedback endpoints. Empty data shows an empty state, never placeholder numbers.
  - Responsive by layout, not by separate apps: full sidebar ≥1024 px, icon rail on tablets, top
    bar, bottom navigation and drawers on phones; `100dvh`, safe-area padding, focus-trapped
    dialogs that become bottom sheets on phones; animations use only transform and opacity, and
    `prefers-reduced-motion` turns them off.
- **Alternatives:** a component library (MUI/shadcn) or Framer Motion: faster to start, but heavier
  and less distinctive. CSS keyframes cover every animation needed here.
- **Consequences:** about 140 KB of gzipped JS, mostly React and the Markdown renderer.

## 16. Alternatives considered (summary)

| Area | Chosen | Rejected | Why |
|---|---|---|---|
| Agent framework | ~200-line own loop | LangChain/LangGraph | The loop needs persistence, interception and offline parity; a framework would hide exactly the parts being assessed |
| Tool execution | Manual | SDK automatic calling | Would bypass authorisation, confirmation and audit |
| Retrieval | FTS5/BM25 | Vector DB | Tiny corpus; explainability; zero infra |
| Confirmation | API action | Typing "yes" | Keeps money movement out of free-text interpretation |
| UI state | React state + hooks | Redux/router libraries | Three pages; no deep links needed |
| Markdown rendering | Plain text | Markdown/HTML renderer | No XSS surface; answers are short |

## 17. Assumptions

- Identity is established upstream; `X-User-Id` / `X-Admin-Key` stand in for it.
- One customer per account (no workspace roles); USD; English seed data (the prompt asks the
  model to reply in the customer's language).
- "My payment failed" means the latest unpaid renewal invoice.
- Billing is a deterministic simulation: a retry succeeds unless the default card is expired;
  3 failed attempts exhaust dunning. Emails and charges are simulated; no real gateway is involved.
- Nimbus, its policies and customers are fictional.

## 18. Trade-offs

| Decision | Gained | Gave up |
|---|---|---|
| Model-driven tool selection | Multi-step flows, paraphrase robustness | Some predictability and cost; offset by deterministic diagnosis, confirmation and evals |
| Commit mid-turn | No lock held during model calls | If Gemini fails with fallback disabled, the user message and completed tool effects persist without a reply (the effects are real, so this is the honest record) |
| Text-only history | Small context | Possible repeated lookups |
| Synchronous FastAPI + SQLAlchemy | Simplicity | A Gemini call occupies a worker thread |
| SQLite | No setup | Single writer |

## 19. Current limitations

- Demo authentication only; no rate limiting; no PII redaction in `tool_invocations`.
- No streaming; a Gemini turn with tools takes several seconds (see measured latency), and the UI
  can show only one honest loading message.
- Response cards are snapshots of the state when the answer was given (an "Unpaid" card stays
  unpaid in history after a later successful retry; the confirmation card and the follow-up
  message show the new state).
- The UI keeps demo settings (customer, admin key, evaluation mode) in `localStorage`. Fine for a
  demo; real sessions would use HTTP-only cookies.
- Visual checks were done in Chromium at 320, 375, 768, 1280 and 1440 px; Safari, Firefox and real
  devices were not tested.
- Lexical retrieval at whole-article granularity.
- Offline rules are English keyword heuristics (4 known misses in the eval).
- No migrations: tables are created on startup; schema changes need `make reset` locally (Alembic
  in production).
- The eval measures routing, tool use, key facts and side effects. Answer quality beyond that is
  judged manually against the criteria in docs/evaluation.md.

## 20. With another week

1. Turn thumbs-down feedback into new eval cases automatically; add an LLM-as-judge for
   groundedness and tone; run evals in CI on every prompt or model change.
2. Hybrid retrieval (BM25 + embeddings), article chunking and versioned articles so each citation
   records the revision it used.
3. Streaming responses (SSE) with tool-progress events in the UI.
4. Real authentication (OIDC/JWT) with an admin role, per-user rate limits, PII redaction.
5. Postgres + Alembic, async I/O, OpenTelemetry traces per turn with cost dashboards.
6. More confirmation-gated flows: change or cancel plan, refund requests routed to humans, and a
   "card updated" webhook that retries the unpaid invoice automatically.
7. Summarise long conversations instead of a fixed 20-message window.
