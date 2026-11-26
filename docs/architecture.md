# Architecture

All diagrams reflect the code as it is. File and class names are given so each box can be traced
to its implementation.

## 1. Components

```mermaid
flowchart TB
    ui["React UI (frontend/)<br/>chat · knowledge base · analytics<br/>served by FastAPI from frontend/dist"]

    subgraph api["API layer — app/api"]
        routes["Routers: kb · chat · conversations · actions · feedback · /health"]
        deps["deps.py: demo auth (X-User-Id, X-Admin-Key)<br/>one DB session per request"]
        errs["main.py: AppError → {error:{code,message,details}}"]
    end

    subgraph svc["Services — app/services"]
        chat["ChatService"]
        actions["ActionService + DBActionGate"]
        kbs["KnowledgeBaseService"]
        fbs["FeedbackService"]
    end

    subgraph agent["Agent — app/agent"]
        loop["SupportAgent (agent.py)<br/>bounded loop · validation · confirmation gate<br/>route derivation · citation filter · fallback"]
        tools["ToolRegistry: 7 tools (tools/support_tools.py)"]
        retr["FTSRetriever (retriever.py)"]
        subgraph prov["LLMProvider (llm/)"]
            gem["GeminiProvider<br/>google-genai, manual function calling"]
            off["OfflineProvider<br/>deterministic rules"]
        end
    end

    subgraph be["Backend interfaces — app/backend"]
        ifc["AccountService · BillingService · TicketService"]
        mock["Mock implementations (mock.py)<br/>deterministic, DB-backed"]
    end

    repos["Repositories — app/repositories"]
    db[("SQLite (WAL, FKs on)<br/>support tables · mock billing tables · kb_articles_fts")]
    gapi(["Google Gemini API"])

    ui --> routes --> svc
    chat --> loop
    loop --> prov
    gem --> gapi
    loop --> tools --> retr & ifc
    ifc -.implemented by.-> mock --> db
    actions --> tools
    svc --> repos --> db
    retr --> repos
```

`app/container.py` is the composition root: it chooses the provider from configuration
(`build_providers`) and builds per-request services. Nothing else instantiates concrete classes.

## 2. Agent execution flow (one chat turn)

```mermaid
flowchart TD
    A["POST /api/v1/chat<br/>Pydantic validation (1-4000 chars)"] --> B["deps: X-User-Id → User (401 if unknown)"]
    B --> C["ChatService: load or create conversation<br/>(ownership in the query → 404 for others)"]
    C --> D["save user message + request_id, COMMIT<br/>(no write lock held during model calls)"]
    D --> E["SupportAgent.run<br/>history = last 20 messages"]
    E --> F{"provider.complete()<br/>Gemini"}
    F -- "function calls" --> G["for each call:<br/>known tool? args valid (Pydantic, extra=forbid)?<br/>identical read already done? reuse"]
    G --> H{"requires_confirmation?"}
    H -- yes --> I["describe() re-checks eligibility<br/>create PendingAction (15 min TTL)<br/>tell model: awaiting confirmation"]
    H -- no --> J["tool.run(args, ctx) with ctx.user_id<br/>errors → is_error result, never a 500"]
    I & J --> K["record ToolInvocation · checkpoint COMMIT"]
    K --> L{"round < 5?"}
    L -- yes --> F
    L -- no --> M["stop: polite 'shall I open a ticket?'"]
    F -- "text, no calls" --> N["keep only [KB-n] citations that were retrieved<br/>derive route from tool categories"]
    F -- "LLMUnavailableError" --> O{"fallback configured?"}
    O -- yes --> P["OfflineProvider continues the SAME transcript<br/>(completed tools reported, not repeated)<br/>degraded = true, reason recorded"]
    P --> N
    O -- no --> Q["503 llm_unavailable"]
    M & N --> R["save assistant message + trace fields<br/>link pending actions · return ChatResponse"]
```

Limits per turn: at most 5 tool rounds, so at most 6 model calls. The SDK retries 429/5xx up to
`GEMINI_MAX_RETRIES` times with backoff, under a `GEMINI_TIMEOUT_SECONDS` timeout.

## 3. Knowledge retrieval

```mermaid
flowchart LR
    q["Gemini: search_knowledge_base(query)"] --> n["build_fts_query: lowercase, drop stopwords,<br/>quote every term, OR them<br/>(user text can't inject FTS syntax)"]
    n --> f["kb_articles_fts MATCH …<br/>ORDER BY bm25(title×5, content×1, tags×2)"]
    f --> p["join kb_articles, keep is_published,<br/>drop score ≤ KB_MIN_RELEVANCE, top 3"]
    p --> r["tool result: id, title, category, content (≤1500 chars)<br/>citations = returned ids"]
    r --> m["model answers with [KB-id] markers"]
    m --> v["agent keeps only markers whose id was returned<br/>→ messages.citations"]
    w["Admin edits article (PATCH)"] --> t["AFTER UPDATE trigger re-indexes"] --> f
```

## 4. Backend tool execution

```mermaid
flowchart LR
    call["ToolCall(name, args)"] --> reg{"in ToolRegistry?"}
    reg -- no --> e1["error: Unknown tool"]
    reg -- yes --> val{"Args.model_validate<br/>(extra=forbid)"}
    val -- invalid --> e2["error: Invalid arguments"]
    val -- ok --> gate{"requires_confirmation?"}
    gate -- yes --> pa["PendingAction (not executed)"]
    gate -- no --> run["Tool.run(args, ToolContext)"]
    run --> svc["AccountService / BillingService / TicketService<br/>(always scoped to ctx.user_id)"]
    svc -- AppError --> e3["error result (business message)"]
    svc -- unexpected --> e4["error: Internal error (logged)"]
    svc -- ok --> ok["ToolResult(ok, data, summary, citations)"]
```

Tool categories (`knowledge`, `read`, `action`, `escalation`) drive the route label and the
"reuse identical reads" optimisation.

## 5. Payment failure and confirmation

```mermaid
sequenceDiagram
    autonumber
    participant U as Customer (UI)
    participant API as FastAPI
    participant A as SupportAgent
    participant G as Gemini
    participant B as BillingService (mock)
    participant DB as SQLite

    U->>API: POST /chat "My payment failed" (X-User-Id: 3)
    API->>A: run(ctx user=3)
    A->>G: system + history + 7 function declarations
    G-->>A: get_payment_issue()
    A->>B: get_payment_issue(user=3)
    Note over B: rules: card expired → update_payment_method<br/>valid card + retries left → retry_payment<br/>retries exhausted → escalate_to_human<br/>no unpaid invoice → none
    B-->>A: INV-3003, insufficient_funds, recommended: retry_payment
    A->>G: FunctionResponse
    G-->>A: retry_payment(invoice_number="INV-3003")
    Note over A: requires_confirmation → NOT executed
    A->>B: re-check eligibility (describe)
    A->>DB: PendingAction(status=pending, expires +15 min)
    A->>G: {status: awaiting_customer_confirmation}
    G-->>A: "…press Confirm to retry 199.00 USD"
    API-->>U: reply + actions[{id, summary, status: pending}]
    U->>API: POST /actions/{id}/confirm
    API->>DB: UPDATE … SET status=confirmed WHERE id=? AND user_id=?<br/>AND status='pending' AND expires_at>now
    alt claimed (rowcount = 1)
        API->>B: re-check eligibility, then retry_payment (no LLM)
        B->>DB: payment attempt · invoice paid · subscription active
        API-->>U: action confirmed + outcome message saved to history
    else already used / expired / cancelled
        API-->>U: 409 {status}
    end
```

## 6. Fallback and failure handling

```mermaid
flowchart TD
    s["Gemini call"] --> e{"outcome"}
    e -- "429 RESOURCE_EXHAUSTED" --> r1["SDK retries with backoff → still failing:<br/>LLMUnavailableError(reason=rate_limited)"]
    e -- "5xx / timeout / network" --> r2["LLMUnavailableError(server_error | unreachable)"]
    e -- "MALFORMED_FUNCTION_CALL<br/>empty response<br/>truncated function call" --> r3["LLMUnavailableError(malformed | empty | truncated)<br/>(a truncated call is never executed)"]
    e -- "SAFETY / blocked prompt" --> r4["safe refusal text, no tools"]
    e -- "401/403/404" --> r5["LLMUnavailableError(auth | model_not_found)"]
    r1 & r2 & r3 & r5 --> f{"AI_DEGRADE_TO_OFFLINE?"}
    f -- yes --> o["OfflineProvider finishes the same turn<br/>degraded=true, fallback_reason saved<br/>visible in the Details panel (Evaluation mode)"]
    f -- no --> x["HTTP 503 {code: llm_unavailable}<br/>user message + completed effects already committed"]
```

Startup: `AI_PROVIDER=gemini` without `GEMINI_API_KEY` raises `ConfigurationError` immediately;
`AI_PROVIDER=auto` without a key runs offline.
