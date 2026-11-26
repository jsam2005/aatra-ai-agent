"""The concrete tools the support agent can use."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from app.backend.interfaces import RetryNotAllowedError
from app.models.enums import ToolCategory


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------- knowledge ----------------


class SearchKBArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=300, description="Keywords describing what the customer wants to know.")


class SearchKnowledgeBase(Tool):
    name = "search_knowledge_base"
    category = ToolCategory.KNOWLEDGE
    Args = SearchKBArgs
    description = (
        "Search the help-center knowledge base for product, policy and how-to information "
        "(refunds, plans and pricing, billing rules, account settings, security, troubleshooting). "
        "Use it for any general question that does not depend on this customer's own account data. "
        "Returns the most relevant articles with their ids."
    )

    def run(self, args: SearchKBArgs, ctx: ToolContext) -> ToolResult:
        docs = ctx.retriever.search(args.query, k=3)
        if not docs:
            return ToolResult(True, {"articles": [], "note": "No relevant article found."}, "No KB article matched.")
        articles = [{"id": d.id, "title": d.title, "category": d.category, "content": d.content} for d in docs]
        return ToolResult(
            True,
            {"articles": articles},
            f"Found {len(docs)} article(s); best match: '{docs[0].title}'.",
            citations=[d.id for d in docs],
        )


# ---------------- reads ----------------


class GetSubscription(Tool):
    name = "get_subscription"
    category = ToolCategory.READ
    description = (
        "Get the signed-in customer's current subscription: plan, price, billing interval, seats, "
        "status (trialing/active/past_due/cancelled) and current billing period."
    )

    def run(self, args, ctx: ToolContext) -> ToolResult:
        sub = ctx.billing.get_subscription(ctx.user_id)
        if sub is None:
            return ToolResult(
                True, {"subscription": None, "message": "This account has no subscription."}, "You don't have a subscription yet."
            )
        data = {
            "plan": sub.plan_name,
            "plan_code": sub.plan_code,
            "price": sub.price,
            "interval": sub.interval,
            "seats": sub.seats,
            "status": sub.status,
            "current_period_start": _iso(sub.current_period_start),
            "current_period_end": _iso(sub.current_period_end),
            "cancel_at_period_end": sub.cancel_at_period_end,
        }
        renew = "ends" if sub.cancel_at_period_end else "renews"
        return ToolResult(
            True,
            {"subscription": data},
            f"You're on the {sub.plan_name} plan ({sub.price}/{sub.interval}, {sub.seats} seat(s)), "
            f"status '{sub.status}'. It {renew} on {sub.current_period_end:%d %b %Y}.",
        )


class ListInvoices(Tool):
    name = "list_invoices"
    category = ToolCategory.READ
    description = "List the signed-in customer's most recent invoices with amount, status and dates."

    def run(self, args, ctx: ToolContext) -> ToolResult:
        invoices = ctx.billing.list_invoices(ctx.user_id, limit=5)
        rows = [
            {"number": i.number, "amount": i.amount, "status": i.status, "issued_on": _iso(i.issued_on), "paid_at": _iso(i.paid_at)}
            for i in invoices
        ]
        if not rows:
            return ToolResult(True, {"invoices": [], "message": "This account has no invoices."}, "You don't have any invoices yet.")
        lines = "; ".join(f"{r['number']} {r['amount']} ({r['status']}, {r['issued_on']})" for r in rows)
        return ToolResult(True, {"invoices": rows}, f"Your recent invoices: {lines}.")


class GetPaymentIssue(Tool):
    name = "get_payment_issue"
    category = ToolCategory.READ
    description = (
        "Diagnose a failed or missing payment for the signed-in customer. Returns the unpaid invoice, "
        "the decline reason, the card on file, how many automatic retries remain, and a "
        "`recommended_action` (update_payment_method | retry_payment | escalate_to_human) that you "
        "must follow. Call this first whenever the customer mentions a failed, declined or missing payment."
    )

    def run(self, args, ctx: ToolContext) -> ToolResult:
        issue = ctx.billing.get_payment_issue(ctx.user_id)
        if issue is None:
            # Explicit status + message: a bare {"issue": null} was misread by a live model as
            # "unknown" and it invented a failure (eval case pay-none).
            msg = "No failed or unpaid payment found: every invoice on this account is paid."
            return ToolResult(
                True,
                {"issue": None, "status": "no_unpaid_invoices", "message": msg},
                "I checked your account and there are no unpaid invoices — all payments are up to date.",
            )
        pm = issue.payment_method
        data = {
            "invoice_number": issue.invoice_number,
            "amount": issue.amount,
            "failed_attempts": issue.failed_attempts,
            "last_decline_code": issue.last_decline_code,
            "last_attempt_at": _iso(issue.last_attempt_at),
            "retries_remaining": issue.retries_remaining,
            "payment_method": (
                {"brand": pm.brand, "last4": pm.last4, "expires": pm.expires, "is_expired": pm.is_expired} if pm else None
            ),
            "recommended_action": issue.recommended_action,
            "explanation": issue.explanation,
        }
        return ToolResult(
            True,
            {"issue": data},
            f"Invoice {issue.invoice_number} for {issue.amount} is unpaid after {issue.failed_attempts} failed "
            f"attempt(s). {issue.explanation}",
        )


# ---------------- actions ----------------


class SendPasswordReset(Tool):
    name = "send_password_reset"
    category = ToolCategory.ACTION
    description = (
        "Email a password-reset link to the signed-in customer's registered email address. "
        "Safe to call directly when the customer asks to reset their password or cannot log in: "
        "the link only ever goes to the address already on the account."
    )

    def run(self, args, ctx: ToolContext) -> ToolResult:
        res = ctx.account.send_password_reset(ctx.user_id)
        data = {
            "sent_to": res.sent_to,
            "link_valid_for": "1 hour",
            "already_sent_recently": res.already_sent_recently,
            "simulated": True,
        }
        if res.already_sent_recently:
            summary = f"A reset link was already sent to {res.sent_to} a few minutes ago; it is still valid, so please check that inbox (and spam)."
        else:
            summary = f"I've sent a password reset link to {res.sent_to}. It expires in 1 hour. (Demo: the email is simulated.)"
        return ToolResult(True, data, summary)


class RetryPaymentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_number: str = Field(description="The unpaid invoice number returned by get_payment_issue, e.g. INV-1003.")


class RetryPayment(Tool):
    name = "retry_payment"
    category = ToolCategory.ACTION
    Args = RetryPaymentArgs
    requires_confirmation = True
    description = (
        "Charge the customer's card on file again for an unpaid invoice. Moves money, so it is NOT "
        "executed immediately: the customer is shown a confirmation button. Only call it when "
        "get_payment_issue recommended retry_payment. After calling it, tell the customer to confirm; "
        "never say the payment went through."
    )

    def describe(self, args: RetryPaymentArgs, ctx: ToolContext) -> str:
        # Validate at proposal time so the customer is never shown a Confirm button that can't work.
        issue = ctx.billing.get_payment_issue(ctx.user_id)
        if issue is None or issue.invoice_number != args.invoice_number:
            raise RetryNotAllowedError(f"{args.invoice_number} is not an unpaid invoice on this account.")
        if issue.recommended_action != "retry_payment":
            raise RetryNotAllowedError(f"A retry is not possible right now: {issue.explanation}")
        pm = issue.payment_method
        return f"Charge {issue.amount} for invoice {issue.invoice_number} to {pm.brand} ending {pm.last4}"

    def run(self, args: RetryPaymentArgs, ctx: ToolContext) -> ToolResult:
        # Re-check eligibility at execution time: the card may have expired or retries run out
        # since the customer saw the Confirm button. (An already-paid invoice is handled by
        # the billing service idempotently.)
        issue = ctx.billing.get_payment_issue(ctx.user_id)
        if issue and issue.invoice_number == args.invoice_number and issue.recommended_action != "retry_payment":
            raise RetryNotAllowedError(f"A retry is no longer possible: {issue.explanation}")
        res = ctx.billing.retry_payment(ctx.user_id, args.invoice_number)
        data = {"invoice_number": res.invoice_number, "succeeded": res.succeeded, "decline_code": res.decline_code, "amount": res.amount}
        if res.succeeded:
            return ToolResult(True, data, f"Payment successful: {res.message} Your subscription is active again.")
        return ToolResult(
            False, data, f"The retry for invoice {res.invoice_number} failed ({res.decline_code}). Please update your payment method and try again."
        )


class EscalateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(max_length=200, description="Short subject line for the support ticket.")
    summary: str = Field(max_length=2000, description="What the customer needs and what has already been tried.")
    priority: Literal["low", "normal", "high"] = Field(description="high for billing failures, security or angry customers.")


class EscalateToHuman(Tool):
    name = "escalate_to_human"
    category = ToolCategory.ESCALATION
    Args = EscalateArgs
    description = (
        "Open a support ticket so a human agent follows up by email. Use when the customer asks for a "
        "person, when get_payment_issue recommends it, when the request needs judgement you cannot "
        "apply (refund exceptions, disputes, security incidents, legal/data requests), or when you "
        "cannot resolve the issue with the other tools."
    )

    def run(self, args: EscalateArgs, ctx: ToolContext) -> ToolResult:
        t = ctx.tickets.create_ticket(ctx.user_id, ctx.conversation_id, args.subject, args.summary, args.priority)
        data = {"ticket_reference": t.reference, "priority": t.priority, "status": t.status, "already_open": t.already_open}
        if t.already_open:
            return ToolResult(True, data, f"Your ticket {t.reference} is already open; a support specialist will reply by email.")
        return ToolResult(
            True,
            data,
            f"I've opened ticket {t.reference} ({t.priority} priority). A support specialist will reply by email, usually within one business day.",
        )


def default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            SearchKnowledgeBase(),
            GetSubscription(),
            ListInvoices(),
            GetPaymentIssue(),
            SendPasswordReset(),
            RetryPayment(),
            EscalateToHuman(),
        ]
    )
