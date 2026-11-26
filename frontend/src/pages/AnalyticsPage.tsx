import { BarChart3, MessageSquare, RefreshCw, Smile, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Badge, Button, Card, PageHeader, Spinner } from "../components/ui";
import { fmtShortDate, pct, routeLabel, toolLabel } from "../lib/format";
import { ApiError, api } from "../services/api";
import type { AnalyticsOverview, FeedbackItem, FeedbackSummary } from "../types/api";
import { AdminRequired } from "./KnowledgePage";

interface Data {
  overview: AnalyticsOverview;
  summary: FeedbackSummary;
  recent: FeedbackItem[];
}

// Every number on this page comes from stored conversations, tool calls and feedback.
export function AnalyticsPage({ adminKey, onOpenSettings }: { adminKey: string; onOpenSettings: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [overview, summary, recent] = await Promise.all([api.analyticsOverview(adminKey), api.feedbackSummary(adminKey), api.recentFeedback(adminKey)]);
      setData({ overview, summary, recent: recent.items });
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  }, [adminKey]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && (error.status === 401 || error.status === 403)) return <AdminRequired onOpenSettings={onOpenSettings} />;

  return (
    <div className="mx-auto h-full max-w-6xl overflow-y-auto px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader
        title="Feedback Analytics"
        description="How customers rate the assistant's answers, and what it did to produce them."
        action={
          <Button onClick={load} disabled={loading}>
            {loading ? <Spinner /> : <RefreshCw className="size-4" />} Refresh
          </Button>
        }
      />

      {error && <p className="rounded-2xl border border-line bg-white p-4 text-sm text-hot">{error.message}</p>}
      {!data && loading && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">{Array.from({ length: 5 }, (_, i) => <div key={i} className="skeleton h-28 rounded-[20px]" />)}</div>
      )}

      {data && (
        <div className="animate-fade-up space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Conversations" value={data.overview.conversations} icon={<MessageSquare className="size-4" />} />
            <Stat label="AI responses" value={data.overview.responses} icon={<BarChart3 className="size-4" />} />
            <Stat label="Helpful" value={data.summary.up} icon={<ThumbsUp className="size-4" />} />
            <Stat label="Not helpful" value={data.summary.down} icon={<ThumbsDown className="size-4" />} />
            <Stat label="Satisfaction" value={pct(data.summary.satisfaction)} icon={<Smile className="size-4" />} highlight />
          </div>

          <div className="grid gap-4 lg:grid-cols-5">
            <Card className="p-5 lg:col-span-3">
              <SectionTitle title="Feedback trend" note="Ratings per day, last 14 days" />
              <Trend days={data.overview.feedback_by_day} />
            </Card>
            <Card className="p-5 lg:col-span-2">
              <SectionTitle title="Response categories" note="Answers by how they were produced" />
              {data.overview.responses_by_route.length === 0 ? (
                <Empty text="No answers yet. Start a conversation in AI Chat." />
              ) : (
                <Bars
                  rows={data.overview.responses_by_route.map((r) => {
                    const sat = data.summary.by_route.find((s) => s.route === r.route);
                    return { label: routeLabel(r.route), value: r.count, note: sat ? `${pct(sat.satisfaction)} helpful` : "not rated" };
                  })}
                />
              )}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-5">
            <Card className="overflow-hidden lg:col-span-3">
              <div className="p-5 pb-3">
                <SectionTitle title="Backend operations" note="Tool calls made by the assistant" />
              </div>
              {data.overview.tools.length === 0 ? (
                <div className="px-5 pb-5"><Empty text="No operations yet." /></div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-sm">
                    <thead className="bg-surface text-left text-xs text-muted">
                      <tr>
                        <th className="px-5 py-2 font-medium">Operation</th>
                        <th className="px-3 py-2 text-right font-medium">Calls</th>
                        <th className="px-3 py-2 text-right font-medium">Succeeded</th>
                        <th className="px-3 py-2 text-right font-medium">Awaiting</th>
                        <th className="px-3 py-2 text-right font-medium">Errors</th>
                        <th className="px-5 py-2 text-right font-medium">Avg time</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {data.overview.tools.map((t) => (
                        <tr key={t.tool_name}>
                          <td className="px-5 py-2.5 font-medium text-ink"><Wrench className="mr-2 inline size-3.5 text-magenta" />{toolLabel(t.tool_name)}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums">{t.calls}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums text-success">{t.succeeded}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums text-warning">{t.awaiting_confirmation}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums text-hot">{t.errors}</td>
                          <td className="px-5 py-2.5 text-right tabular-nums text-muted">{t.avg_duration_ms !== null ? `${t.avg_duration_ms} ms` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <Card className="p-5 lg:col-span-2">
              <SectionTitle title="Recent feedback" note="Latest ratings from customers" />
              {data.recent.length === 0 ? (
                <Empty text="Rate answers with the thumbs buttons in AI Chat to see them here." />
              ) : (
                <ul className="divide-y divide-line/60">
                  {data.recent.map((f) => (
                    <li key={f.id} className="flex gap-3 py-2.5">
                      <span className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full ${f.rating === "up" ? "bg-emerald-50 text-success" : "bg-blush text-hot"}`}>
                        {f.rating === "up" ? <ThumbsUp className="size-3.5" /> : <ThumbsDown className="size-3.5" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 text-sm text-ink">{f.message_excerpt}</p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                          <Badge>{routeLabel(f.route)}</Badge>
                          {fmtShortDate(f.created_at)}
                          {f.comment && <span className="italic">“{f.comment}”</span>}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, icon, highlight = false }: { label: string; value: number | string; icon: ReactNode; highlight?: boolean }) {
  return (
    <div className={`rounded-[20px] p-4 transition-transform duration-200 hover:-translate-y-0.5 ${highlight ? "bg-brand gloss col-span-2 text-white lg:col-span-1" : "border border-line/80 bg-white shadow-soft"}`}>
      <div className={`flex items-center justify-between text-xs font-medium ${highlight ? "text-white/80" : "text-muted"}`}>
        {label}
        <span className={`flex size-7 items-center justify-center rounded-full ${highlight ? "bg-white/15" : "bg-blush text-magenta"}`}>{icon}</span>
      </div>
      <p className="mt-3 text-2xl font-semibold leading-none tracking-tight tabular-nums sm:text-[28px]">{value}</p>
    </div>
  );
}

function SectionTitle({ title, note }: { title: string; note: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      <p className="text-xs text-muted">{note}</p>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="rounded-2xl bg-surface px-4 py-6 text-center text-sm text-muted">{text}</p>;
}

function Bars({ rows }: { rows: { label: string; value: number; note: string }[] }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <ul className="space-y-3">
      {rows.map((r, i) => (
        <li key={r.label}>
          <div className="flex items-baseline justify-between gap-2 text-sm">
            <span className="truncate text-ink">{r.label}</span>
            <span className="shrink-0 text-xs tabular-nums text-muted">{r.value} · {r.note}</span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-blush">
            <div className="bg-brand h-full origin-left rounded-full animate-[grow_600ms_var(--ease-out-soft)_both]" style={{ width: `${(r.value / max) * 100}%`, animationDelay: `${i * 60}ms` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Trend({ days }: { days: { date: string; up: number; down: number }[] }) {
  const total = days.reduce((n, d) => n + d.up + d.down, 0);
  if (total === 0) return <Empty text="No ratings in the last 14 days yet." />;
  const max = Math.max(...days.map((d) => d.up + d.down), 1);
  return (
    <div>
      <div className="flex h-40 items-end gap-1.5" role="img" aria-label={`${total} ratings over the last 14 days`}>
        {days.map((d, i) => {
          const h = ((d.up + d.down) / max) * 100;
          return (
            <div key={d.date} className="group relative flex h-full flex-1 flex-col justify-end" title={`${fmtShortDate(d.date)}: ${d.up} helpful, ${d.down} not helpful`}>
              <div className="flex origin-bottom flex-col overflow-hidden rounded-md animate-[rise_500ms_var(--ease-out-soft)_both]" style={{ height: `${h}%`, animationDelay: `${i * 25}ms` }}>
                <div className="bg-hot/85" style={{ flex: d.down }} />
                <div className="bg-brand" style={{ flex: d.up }} />
              </div>
              {d.up + d.down === 0 && <div className="h-1 rounded bg-blush" />}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-muted">
        <span>{fmtShortDate(days[0].date)}</span>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1"><span className="bg-brand size-2 rounded-full" /> Helpful</span>
          <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-hot/85" /> Not helpful</span>
        </span>
        <span>{fmtShortDate(days[days.length - 1].date)}</span>
      </div>
    </div>
  );
}
