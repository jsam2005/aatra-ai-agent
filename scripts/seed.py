"""Demo data: a small help center for the fictional SaaS "Nimbus" and four customers whose
billing states cover every branch of the payment-failure flow.

    python -m scripts.seed          # seed an empty database
    python -m scripts.seed --reset  # drop everything and re-seed
"""

import argparse
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Invoice, KBArticle, PaymentAttempt, PaymentMethod, Plan, Subscription, User
from app.models.enums import DeclineCode, InvoiceStatus, PaymentAttemptStatus, SubscriptionStatus

KB_ARTICLES = [
    (
        "Refund policy",
        "billing",
        "refund money-back cancel",
        "Nimbus offers a full refund within 14 days of your first payment on any plan, no questions asked. "
        "After 14 days, monthly plans are not refunded, but you keep access until the end of the billing period you paid for. "
        "Annual plans cancelled after 14 days receive a prorated refund for the unused full months. "
        "Refunds go back to the original payment method within 5-10 business days. "
        "To request a refund, contact support from the email address on your account. Refund exceptions are reviewed by our billing team.",
    ),
    (
        "Plans and pricing",
        "billing",
        "pricing plans starter pro business seats",
        "Nimbus has three plans. Starter costs 12 USD per month for 1 seat and includes unlimited projects. "
        "Pro costs 49 USD per month for up to 5 seats and adds time tracking, integrations and priority email support. "
        "Business costs 199 USD per month for up to 25 seats and adds SSO, audit logs and a 99.9% uptime SLA. "
        "Annual billing gives two months free on every plan.",
    ),
    (
        "How billing and renewals work",
        "billing",
        "renewal billing-cycle invoice auto-renew",
        "Subscriptions renew automatically at the start of each billing period and the card on file is charged on the renewal date. "
        "An invoice is emailed for every charge. You can see your renewal date and invoices under Settings > Billing.",
    ),
    (
        "Why did my payment fail?",
        "billing",
        "payment failed declined dunning past-due retry",
        "Payments usually fail because the card has expired, the bank declined the charge (for example insufficient funds), "
        "or the issuer flagged it. When a renewal payment fails your subscription becomes past due and we retry the charge "
        "automatically up to 3 times over 7 days. Your workspace stays fully available during this period. "
        "If all retries fail, the account is reviewed by our billing team before any access is restricted. "
        "Updating your card or retrying the payment resolves most cases immediately.",
    ),
    (
        "Update your payment method",
        "billing",
        "card payment-method update expired credit-card",
        "To update your card, go to Settings > Billing > Payment method and click Replace card. "
        "Enter the new card details and save. If you have an unpaid invoice, we automatically retry it with the new card within a few minutes. "
        "Only workspace owners can change the payment method.",
    ),
    (
        "Cancel your subscription",
        "billing",
        "cancel downgrade close-account",
        "Workspace owners can cancel under Settings > Billing > Cancel subscription. "
        "Cancellation takes effect at the end of the current billing period and you keep access until then. "
        "Your data is kept for 30 days after the subscription ends so you can export it or reactivate.",
    ),
    (
        "Upgrading or downgrading your plan",
        "billing",
        "upgrade downgrade change-plan proration",
        "You can change plans any time under Settings > Billing > Change plan. Upgrades take effect immediately and you are "
        "charged a prorated amount for the rest of the period. Downgrades take effect at the next renewal.",
    ),
    (
        "Reset your password",
        "account",
        "password reset login forgot locked",
        "Click 'Forgot password' on the login page, or ask our support assistant to send a reset link. "
        "The link is emailed to the address on your account and is valid for 1 hour. "
        "If you don't see it, check your spam folder. For security, we never send reset links to a different address.",
    ),
    (
        "Two-factor authentication (2FA)",
        "security",
        "2fa two-factor mfa authenticator security",
        "Enable 2FA under Settings > Security using any authenticator app. Save your backup codes when you enable it. "
        "If you lose access to your authenticator and your backup codes, contact support; identity verification is required to remove 2FA.",
    ),
    (
        "Exporting your data",
        "account",
        "export csv backup data download",
        "Workspace owners can export all projects, tasks and comments as CSV or JSON from Settings > Data > Export. "
        "Large exports are emailed as a download link within an hour.",
    ),
    (
        "Security and data privacy",
        "security",
        "security privacy gdpr encryption soc2",
        "All data is encrypted in transit (TLS 1.2+) and at rest (AES-256). Nimbus is SOC 2 Type II certified and GDPR compliant. "
        "Data is hosted in the EU or US depending on the region chosen at signup. To request deletion of personal data, contact support.",
    ),
    (
        "Contacting support",
        "general",
        "support contact hours human agent ticket",
        "Our support team is available Monday to Friday, 9:00-18:00 CET. Pro and Business plans get priority email support "
        "with a first response within 4 business hours; Starter within 1 business day. The support assistant can open a ticket for you at any time.",
    ),
]


def _seed_kb(session: Session) -> None:
    for title, category, tags, content in KB_ARTICLES:
        session.add(KBArticle(title=title, category=category, tags=tags, content=content, is_published=True))


def _seed_customers(session: Session) -> None:
    today = utcnow().date()
    period_start = today.replace(day=1)
    period_end = (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    starter = Plan(code="starter_monthly", name="Starter", price_cents=1200, seats=1)
    pro = Plan(code="pro_monthly", name="Pro", price_cents=4900, seats=5)
    business = Plan(code="business_monthly", name="Business", price_cents=19900, seats=25)
    session.add_all([starter, pro, business])
    session.flush()

    def customer(uid, name, email, plan, status, card_exp: date, failures: list[DeclineCode]):
        session.add(User(id=uid, name=name, email=email))
        session.flush()  # no ORM relationship orders these inserts, so make the FK target exist first
        sub = Subscription(user_id=uid, plan_id=plan.id, status=status, current_period_start=period_start, current_period_end=period_end)
        card = PaymentMethod(user_id=uid, brand="Visa", last4=f"{4240 + uid}", exp_month=card_exp.month, exp_year=card_exp.year)
        session.add_all([sub, card])
        session.flush()
        # two months of paid history
        for i, months_back in enumerate((2, 1), start=1):
            issued = (period_start - timedelta(days=31 * months_back)).replace(day=1)
            inv = Invoice(
                user_id=uid, subscription_id=sub.id, number=f"INV-{uid}{i:03d}", amount_cents=plan.price_cents,
                status=InvoiceStatus.PAID, issued_on=issued, paid_at=datetime.combine(issued, time(9, 0)),
            )
            session.add(inv)
            session.flush()
            session.add(PaymentAttempt(invoice_id=inv.id, payment_method_id=card.id, status=PaymentAttemptStatus.SUCCEEDED, attempted_at=inv.paid_at))
        # current period
        current = Invoice(
            user_id=uid, subscription_id=sub.id, number=f"INV-{uid}003", amount_cents=plan.price_cents,
            status=InvoiceStatus.PAYMENT_DUE if failures else InvoiceStatus.PAID, issued_on=period_start,
            paid_at=None if failures else utcnow(),
        )
        session.add(current)
        session.flush()
        if not failures:
            session.add(PaymentAttempt(invoice_id=current.id, payment_method_id=card.id, status=PaymentAttemptStatus.SUCCEEDED))
        for n, code in enumerate(failures):
            session.add(
                PaymentAttempt(
                    invoice_id=current.id, payment_method_id=card.id, status=PaymentAttemptStatus.FAILED,
                    decline_code=code, attempted_at=utcnow() - timedelta(days=len(failures) - n),
                )
            )

    future = date(today.year + 2, today.month, 1)
    past = today.replace(day=1) - timedelta(days=40)
    # 1: healthy account
    customer(1, "Asha Raman", "asha@example.com", pro, SubscriptionStatus.ACTIVE, future, [])
    # 2: renewal failed because the card expired -> must update card
    customer(2, "Ben Carter", "ben@example.com", starter, SubscriptionStatus.PAST_DUE, past, [DeclineCode.CARD_EXPIRED])
    # 3: one insufficient-funds decline, card valid -> retry with confirmation
    customer(3, "Chen Wei", "chen@example.com", business, SubscriptionStatus.PAST_DUE, future, [DeclineCode.INSUFFICIENT_FUNDS])
    # 4: retries exhausted -> escalate to a human
    customer(4, "Diana Okafor", "diana@example.com", pro, SubscriptionStatus.PAST_DUE, future, [DeclineCode.CARD_DECLINED] * 3)


def seed(session: Session) -> None:
    _seed_kb(session)
    _seed_customers(session)
    session.flush()


def seed_if_empty(session: Session) -> bool:
    if session.scalar(select(func.count()).select_from(User)):
        return False
    seed(session)
    return True


def main() -> None:
    from app.core.config import get_settings
    from app.db import Base, init_db, make_engine, make_session_factory

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    args = parser.parse_args()

    engine = make_engine(get_settings().database_url)
    if args.reset:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS kb_articles_fts"))
        Base.metadata.drop_all(engine)
    init_db(engine)
    with make_session_factory(engine).begin() as session:
        print("Seeded demo data." if seed_if_empty(session) else "Database already has data; use --reset to re-seed.")


if __name__ == "__main__":
    main()
