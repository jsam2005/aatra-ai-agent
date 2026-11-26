import { AlertTriangle, CalendarClock, CheckCircle2, CreditCard, LifeBuoy, Mail, ReceiptText, ShieldCheck, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { DECLINE_LABELS, fmtDate } from "../lib/format";
import type { ResponseCard } from "../types/api";
import { Badge } from "./ui";

// Every value shown here comes from a tool result the backend returned; nothing is computed or invented.
export function ResponseCards({ cards }: { cards: ResponseCard[] }) {
  if (!cards.length) return null;
  return (
    <div className="mt-3 grid gap-2.5">
      {cards.map((card, i) => (
        <CardSwitch key={`${card.type}-${i}`} card={card} />
      ))}
    </div>
  );
}

function CardSwitch({ card }: { card: ResponseCard }) {
  switch (card.type) {
    case "subscription": {
      const d = card.data;
      return (
        <Shell icon={<Sparkles className="size-4" />} title={`${d.plan ?? "Current"} plan`} badge={<StatusBadge status={d.status} />}>
          <Facts
            items={[
              ["Price", d.price && d.interval ? `${d.price} / ${d.interval}` : d.price],
              ["Seats", d.seats !== undefined ? String(d.seats) : undefined],
              [d.cancel_at_period_end ? "Ends" : "Renews", d.current_period_end ? fmtDate(d.current_period_end) : undefined],
            ]}
          />
        </Shell>
      );
    }
    case "invoices":
      return (
        <Shell icon={<ReceiptText className="size-4" />} title="Recent invoices">
          <ul className="divide-y divide-line/70 text-sm">
            {card.data.invoices.map((inv) => (
              <li key={inv.number} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0">
                  <span className="font-medium text-ink">{inv.number}</span>
                  <span className="ml-2 text-muted">{fmtDate(inv.issued_on)}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="tabular-nums text-ink">{inv.amount}</span>
                  <StatusBadge status={inv.status} />
                </span>
              </li>
            ))}
          </ul>
        </Shell>
      );
    case "payment_issue": {
      const d = card.data;
      if (d.none)
        return (
          <Shell icon={<CheckCircle2 className="size-4" />} title="Payments up to date" badge={<Badge tone="green">All paid</Badge>}>
            <p className="text-sm text-muted">No failed or unpaid invoices on this account.</p>
          </Shell>
        );
      const pm = d.payment_method;
      const next = { update_payment_method: "Update your card", retry_payment: "Retry with confirmation", escalate_to_human: "Specialist review" }[d.recommended_action ?? "escalate_to_human"];
      return (
        <Shell icon={<AlertTriangle className="size-4" />} title={`Payment issue · ${d.invoice_number ?? ""}`} badge={<Badge tone="amber">Unpaid</Badge>}>
          <Facts
            items={[
              ["Amount", d.amount],
              ["Reason", d.last_decline_code ? DECLINE_LABELS[d.last_decline_code] ?? d.last_decline_code : undefined],
              ["Card", pm ? `${pm.brand} •••• ${pm.last4} · ${pm.is_expired ? "expired" : `exp. ${pm.expires}`}` : "No card on file"],
              ["Retries left", d.retries_remaining !== undefined ? String(d.retries_remaining) : undefined],
              ["Next step", next],
            ]}
          />
        </Shell>
      );
    }
    case "password_reset": {
      const d = card.data;
      return (
        <Shell
          icon={<Mail className="size-4" />}
          title={d.already_sent_recently ? "Reset link already sent" : "Password reset link sent"}
          badge={d.simulated ? <Badge>Simulated email</Badge> : undefined}
        >
          <Facts items={[["Sent to", d.sent_to], ["Valid for", d.link_valid_for]]} />
        </Shell>
      );
    }
    case "ticket": {
      const d = card.data;
      return (
        <Shell icon={<LifeBuoy className="size-4" />} title={`Support ticket ${d.ticket_reference ?? ""}`} badge={<Badge tone="pink">{d.already_open ? "Already open" : "Opened"}</Badge>}>
          <Facts items={[["Priority", d.priority ? cap(d.priority) : undefined], ["Status", d.status ? cap(d.status) : undefined], ["Reply", "By email from a specialist"]]} />
        </Shell>
      );
    }
  }
}

function Shell({ icon, title, badge, children }: { icon: ReactNode; title: string; badge?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line/80 bg-surface p-3.5">
      <header className="mb-2 flex items-center gap-2.5">
        <span className="flex size-7 items-center justify-center rounded-lg bg-white text-magenta ring-1 ring-line">{icon}</span>
        <h4 className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">{title}</h4>
        {badge}
      </header>
      {children}
    </section>
  );
}

function Facts({ items }: { items: [string, string | undefined][] }) {
  const shown = items.filter(([, v]) => v !== undefined && v !== "");
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm min-[420px]:grid-cols-2">
      {shown.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 min-[420px]:block">
          <dt className="text-muted">{k}</dt>
          <dd className="font-medium text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const tone = status === "active" || status === "paid" ? "green" : status === "past_due" || status === "payment_due" ? "amber" : "neutral";
  const icon = status === "active" || status === "paid" ? <ShieldCheck className="size-3" /> : status === "trialing" ? <CalendarClock className="size-3" /> : status === "past_due" ? <CreditCard className="size-3" /> : null;
  return <Badge tone={tone}>{icon}{cap(status.replace("_", " "))}</Badge>;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
