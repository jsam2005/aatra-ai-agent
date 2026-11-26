import { CheckCircle2, Clock, CreditCard, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";
import { isExpired } from "../lib/format";
import type { PendingAction } from "../types/api";
import { Badge, Button, Spinner } from "./ui";

interface Props {
  action: PendingAction;
  onConfirm: (id: number) => Promise<void>;
  onCancel: (id: number) => Promise<void>;
}

// The only way a proposed payment runs: an explicit click that calls the confirm endpoint.
// The backend re-validates ownership, expiry, single use and eligibility.
export function ActionCard({ action, onConfirm, onCancel }: Props) {
  const [busy, setBusy] = useState<"confirm" | "cancel" | null>(null);
  const expired = action.status === "expired" || (action.status === "pending" && isExpired(action.expires_at));
  const status = expired ? "expired" : action.status;

  const run = async (kind: "confirm" | "cancel") => {
    if (busy) return;
    setBusy(kind);
    try {
      await (kind === "confirm" ? onConfirm(action.id) : onCancel(action.id));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="relative mt-3 overflow-hidden rounded-2xl border border-line bg-white shadow-soft">
      <div className="h-1 bg-brand" aria-hidden />
      <div className="flex items-start gap-3 p-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand text-white gloss">
          <CreditCard className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-ink">Confirm payment retry</h4>
            <StatusBadge status={status} />
          </div>
          <p className="mt-1 text-sm text-ink">{action.summary}</p>
          <p className="mt-1 text-xs text-muted">Simulated payment for this demo. No real card is charged.</p>

          {status === "pending" && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" disabled={busy !== null} onClick={() => run("confirm")}>
                {busy === "confirm" ? <Spinner /> : <ShieldCheck className="size-4" />} Confirm retry
              </Button>
              <Button variant="secondary" disabled={busy !== null} onClick={() => run("cancel")}>
                {busy === "cancel" && <Spinner />} Cancel
              </Button>
            </div>
          )}
          {status === "expired" && <p className="mt-2 text-xs text-muted">This confirmation expired after 15 minutes. Ask again to get a new one.</p>}
        </div>
      </div>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "pending":
      return <Badge tone="amber"><Clock className="size-3" /> Awaiting you</Badge>;
    case "confirmed":
      return <Badge tone="green"><CheckCircle2 className="size-3" /> Completed</Badge>;
    case "failed":
      return <Badge tone="pink"><XCircle className="size-3" /> Failed</Badge>;
    case "cancelled":
      return <Badge>Cancelled</Badge>;
    default:
      return <Badge>Expired</Badge>;
  }
}
