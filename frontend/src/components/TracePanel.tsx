import { CheckCircle2, Clock, XCircle } from "lucide-react";
import { routeLabel, toolLabel } from "../lib/format";
import type { Message } from "../types/api";

// Evaluation-mode inspector. Safe metadata only: which tools ran and how, never prompts,
// model reasoning or raw tool payloads.
export function TracePanel({ message }: { message: Message }) {
  const tokens =
    message.input_tokens === null && message.output_tokens === null
      ? "not reported"
      : `${message.input_tokens ?? "?"} in · ${message.output_tokens ?? "?"} out`;
  const rows: [string, string][] = [
    ["Route", `${routeLabel(message.route)}${message.route ? ` (${message.route})` : ""}`],
    ["Engine", message.provider === "gemini" ? `Gemini · ${message.model ?? ""}` : message.provider === "offline" ? "Offline rules" : message.provider ?? "—"],
    ["Fallback", message.degraded ? `Yes · ${message.fallback_reason ?? "unavailable"}` : "No"],
    ["Latency", message.latency_ms !== null ? `${message.latency_ms} ms` : "—"],
    ["Model calls", message.model_calls !== null ? String(message.model_calls) : "—"],
    ["Tokens", tokens],
    ["Sources", message.citations.length ? message.citations.map((c) => c.title).join(", ") : "—"],
    ["Request", message.request_id ? message.request_id.slice(0, 12) : "—"],
  ];

  return (
    <div className="animate-fade-up mt-2 rounded-2xl border border-line bg-surface text-xs">
      <p className="border-b border-line/70 px-3.5 py-2 font-semibold uppercase tracking-wide text-[10px] text-muted">Execution trace</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 p-3.5 sm:grid-cols-4">
        {rows.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-muted">{k}</dt>
            <dd className="truncate font-medium text-ink" title={v}>{v}</dd>
          </div>
        ))}
      </dl>
      {message.tool_calls.length > 0 && (
        <ol className="border-t border-line/70 px-3.5 py-2.5">
          {message.tool_calls.map((t, i) => (
            <li key={i} className="flex items-center gap-2 py-1">
              <span className="w-4 text-right tabular-nums text-muted">{i + 1}</span>
              {t.status === "success" ? (
                <CheckCircle2 className="size-3.5 text-success" />
              ) : t.status === "error" ? (
                <XCircle className="size-3.5 text-hot" />
              ) : (
                <Clock className="size-3.5 text-warning" />
              )}
              <span className="font-medium text-ink">{toolLabel(t.tool_name)}</span>
              <code className="hidden truncate text-muted sm:inline">{t.tool_name}{formatArgs(t.arguments)}</code>
              <span className="ml-auto shrink-0 tabular-nums text-muted">{t.duration_ms ?? 0} ms</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatArgs(args: Record<string, unknown>) {
  const entries = Object.entries(args);
  if (!entries.length) return "()";
  return `(${entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ").slice(0, 80)})`;
}
