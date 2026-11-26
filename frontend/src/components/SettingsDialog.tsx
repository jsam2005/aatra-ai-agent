import { Check, Eye, EyeOff, Info } from "lucide-react";
import { useState } from "react";
import { DEMO_CUSTOMERS, initials } from "../services/demo";
import type { Health } from "../types/api";
import { Modal, Switch } from "./ui";

interface Props {
  userId: number;
  onUserChange: (id: number) => void;
  evaluationMode: boolean;
  onEvaluationModeChange: (v: boolean) => void;
  adminKey: string;
  onAdminKeyChange: (v: string) => void;
  health: Health | null;
  onClose: () => void;
}

export function SettingsDialog(p: Props) {
  const [reveal, setReveal] = useState(false);
  return (
    <Modal title="Account & settings" description="Demo controls for reviewing the assignment." onClose={p.onClose} wide>
      <section>
        <h3 className="text-sm font-semibold text-ink">Demo customer</h3>
        <p className="mt-0.5 text-xs text-muted">
          Each seeded Nimbus customer is set up for one scenario. Switching changes the signed-in demo user; the server still
          enforces that you only see that customer's data.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Demo customer">
          {DEMO_CUSTOMERS.map((c) => {
            const active = c.id === p.userId;
            return (
              <button
                key={c.id}
                role="radio"
                aria-checked={active}
                onClick={() => p.onUserChange(c.id)}
                className={`press flex items-center gap-3 rounded-2xl border p-3 text-left transition-colors ${
                  active ? "border-hot/60 bg-blush shadow-[0_0_0_3px_rgb(217_8_137/0.1)]" : "border-line hover:border-hot/30 hover:bg-surface"
                }`}
              >
                <span className={`flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${active ? "bg-brand text-white gloss" : "bg-surface text-berry ring-1 ring-line"}`}>
                  {initials(c.name)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{c.name}</span>
                  <span className="block truncate text-xs text-muted">{c.plan} · {c.scenario}</span>
                </span>
                {active && <Check className="size-4 text-hot" />}
              </button>
            );
          })}
        </div>
      </section>

      <hr className="my-5 border-line/70" />

      <section className="space-y-4">
        <Switch
          checked={p.evaluationMode}
          onChange={p.onEvaluationModeChange}
          label="Evaluation mode"
          description="Shows a Details panel under each answer: route, tools called, sources, latency, tokens and engine. For reviewers; hidden from customers by default."
        />
        {p.evaluationMode && p.health && (
          <div className="flex items-start gap-2 rounded-2xl bg-surface p-3 text-xs text-muted ring-1 ring-line">
            <Info className="mt-0.5 size-3.5 shrink-0 text-magenta" />
            <span>
              Engine: <strong className="text-ink">{p.health.llm_provider === "gemini" ? `Gemini (${p.health.llm_model})` : "offline rules"}</strong>
              {p.health.fallback_provider && <> · falls back to {p.health.fallback_provider} rules if Gemini is unavailable</>}
            </span>
          </div>
        )}
      </section>

      <hr className="my-5 border-line/70" />

      <section>
        <label htmlFor="admin-key" className="text-sm font-semibold text-ink">Admin access</label>
        <p className="mt-0.5 text-xs text-muted">
          Knowledge-base editing and analytics need the admin key (<code>ADMIN_API_KEY</code>). The server checks it on every
          request; this is demo authentication, not production security.
        </p>
        <div className="mt-2 flex items-center gap-2 rounded-full border border-line bg-white pl-4 pr-1.5 focus-within:border-hot/60">
          <input
            id="admin-key"
            type={reveal ? "text" : "password"}
            value={p.adminKey}
            onChange={(e) => p.onAdminKeyChange(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            className="h-10 min-w-0 flex-1 bg-transparent text-sm text-ink focus:outline-none"
          />
          <button onClick={() => setReveal((r) => !r)} className="press rounded-full p-2 text-muted hover:bg-blush" aria-label={reveal ? "Hide key" : "Show key"}>
            {reveal ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </section>

      <p className="mt-6 text-[11px] leading-relaxed text-muted">
        Aatra AI Agent is an independent demonstration built for the Aatra AI Engineering Assignment; it is not an official Aatra
        product. Nimbus is a fictional client, and its payments and emails are simulated.
      </p>
    </Modal>
  );
}
