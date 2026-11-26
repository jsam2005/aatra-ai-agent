import type { Route } from "../types/api";

// Customer-facing wording. Internal identifiers (tool names, route ids) stay out of the default UI.
export const ROUTE_LABELS: Record<Route, string> = {
  knowledge_base: "Help center answer",
  backend_read: "Account lookup",
  backend_action: "Action completed",
  pending_confirmation: "Needs your confirmation",
  escalation: "Handed to a specialist",
  direct: "Conversation",
  error: "Could not complete",
};

export const TOOL_LABELS: Record<string, string> = {
  search_knowledge_base: "Searched help center",
  get_subscription: "Checked subscription",
  list_invoices: "Listed invoices",
  get_payment_issue: "Diagnosed payment",
  send_password_reset: "Sent password reset",
  retry_payment: "Proposed payment retry",
  escalate_to_human: "Opened support ticket",
};

export const DECLINE_LABELS: Record<string, string> = {
  card_expired: "Card expired",
  insufficient_funds: "Insufficient funds",
  card_declined: "Declined by card issuer",
  processing_error: "Temporary processing error",
};

export const routeLabel = (r: Route | null) => (r ? ROUTE_LABELS[r] : "Answer");
export const toolLabel = (t: string) => TOOL_LABELS[t] ?? t;

const asUtc = (iso: string) => new Date(iso.endsWith("Z") || iso.length <= 10 ? iso : `${iso}Z`);

export const fmtTime = (iso: string) => asUtc(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export const fmtDate = (iso: string) => asUtc(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
export const fmtShortDate = (iso: string) => asUtc(iso).toLocaleDateString([], { day: "numeric", month: "short" });
export const isExpired = (iso: string) => asUtc(iso).getTime() <= Date.now();
export const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

/** "Today" / "Yesterday" / "Previous 7 days" / "Older", from real timestamps. */
export function dayGroup(iso: string): string {
  const d = asUtc(iso);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const diff = Math.floor((start.getTime() - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86_400_000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return "Previous 7 days";
  return "Older";
}
