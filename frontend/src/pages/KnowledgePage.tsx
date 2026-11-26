import { ArrowLeft, BookOpen, KeyRound, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Badge, Button, Card, EmptyState, Modal, PageHeader, Spinner } from "../components/ui";
import { useToast } from "../hooks/useToast";
import { fmtDate, fmtShortDate } from "../lib/format";
import { ApiError, api } from "../services/api";
import type { Article, ArticleInput } from "../types/api";

const EMPTY: ArticleInput = { title: "", content: "", category: "", tags: [], is_published: true };

export function KnowledgePage({ adminKey, onOpenSettings }: { adminKey: string; onOpenSettings: () => void }) {
  const toast = useToast();
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [query, setQuery] = useState("");
  const [rankedIds, setRankedIds] = useState<number[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [editing, setEditing] = useState<Article | "new" | null>(null);
  const [deleting, setDeleting] = useState<Article | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.articles(adminKey);
      setForbidden(false);
      setArticles(page.items);
      setSelectedId((id) => (id !== null && page.items.some((a) => a.id === id) ? id : page.items[0]?.id ?? null));
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 401 || err.status === 403) setForbidden(true);
      else toast("error", err.message);
    } finally {
      setLoading(false);
    }
  }, [adminKey, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  // Instant search uses the same ranked FTS endpoint as the agent's tool.
  useEffect(() => {
    if (query.trim().length < 2) {
      setRankedIds(null);
      return;
    }
    const t = setTimeout(() => {
      api.searchArticles(query.trim()).then((hits) => setRankedIds(hits.map((h) => h.id))).catch(() => setRankedIds([]));
    }, 200);
    return () => clearTimeout(t);
  }, [query]);

  const shown = useMemo(() => {
    if (rankedIds === null) return articles;
    const byId = new Map(articles.map((a) => [a.id, a]));
    return rankedIds.map((id) => byId.get(id)).filter((a): a is Article => !!a);
  }, [articles, rankedIds]);
  const selected = articles.find((a) => a.id === selectedId) ?? null;

  const remove = async (a: Article) => {
    try {
      await api.deleteArticle(adminKey, a.id);
      toast("success", `Deleted “${a.title}”`);
      setDeleting(null);
      setMobileDetail(false);
      await load();
    } catch (e) {
      toast("error", (e as ApiError).message);
    }
  };

  if (forbidden) return <AdminRequired onOpenSettings={onOpenSettings} />;

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col overflow-y-auto px-4 py-6 sm:px-8 sm:py-8 lg:overflow-hidden">
      <PageHeader
        title="Knowledge Base"
        description="Manage the information your AI assistant uses to answer customer questions."
        action={
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Plus className="size-4" strokeWidth={2.4} /> New Article
          </Button>
        }
      />

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Card className={`flex min-h-[420px] flex-col overflow-hidden lg:min-h-0 ${mobileDetail ? "max-lg:hidden" : ""}`}>
          <div className="border-b border-line/70 p-3">
            <label className="relative block">
              <span className="sr-only">Search articles</span>
              <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search articles"
                className="h-10 w-full rounded-full border border-line bg-surface pl-10 pr-4 text-sm text-ink placeholder:text-muted focus:border-hot/60 focus:bg-white focus:outline-none"
              />
            </label>
            <p className="mt-2 px-1 text-xs text-muted" aria-live="polite">
              {rankedIds === null ? `${articles.length} articles` : `${shown.length} result${shown.length === 1 ? "" : "s"} · ranked like the assistant's search`}
            </p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading ? (
              <div className="space-y-2 p-1">{Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton h-14 rounded-xl" />)}</div>
            ) : shown.length === 0 ? (
              <EmptyState icon={<BookOpen className="size-5" />} title={query ? "No matching articles" : "No articles yet"}>
                {query ? "The assistant would also find nothing for this search." : "Create the first article to start answering questions."}
              </EmptyState>
            ) : (
              <ul className="space-y-1">
                {shown.map((a) => {
                  const active = selected?.id === a.id;
                  return (
                    <li key={a.id}>
                      <button
                        onClick={() => {
                          setSelectedId(a.id);
                          setMobileDetail(true);
                        }}
                        className={`press w-full rounded-xl px-3 py-2.5 text-left transition-colors ${active ? "bg-blush ring-1 ring-hot/25" : "hover:bg-surface"}`}
                      >
                        <div className="flex items-center gap-2">
                          <span className={`min-w-0 flex-1 truncate text-sm font-medium ${active ? "text-berry" : "text-ink"}`}>{a.title}</span>
                          {!a.is_published && <Badge tone="amber">Draft</Badge>}
                          <span className="shrink-0 text-[11px] text-muted">{fmtShortDate(a.updated_at)}</span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-2">
                          <span className="shrink-0 rounded-full bg-surface px-2 py-px text-[10.5px] font-medium capitalize text-magenta ring-1 ring-line">{a.category}</span>
                          <span className="truncate text-xs text-muted">{a.content}</span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>

        <Card className={`min-h-0 overflow-y-auto ${mobileDetail ? "" : "max-lg:hidden"}`}>
          {selected ? (
            <article key={selected.id} className="animate-fade-up p-5 sm:p-7">
              <button onClick={() => setMobileDetail(false)} className="press -ml-2 mb-3 inline-flex items-center gap-1 rounded-full px-2 py-1 text-sm text-muted hover:bg-blush lg:hidden">
                <ArrowLeft className="size-4" /> All articles
              </button>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h2 className="min-w-0 text-xl font-semibold tracking-tight text-ink">{selected.title}</h2>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => setEditing(selected)}>
                    <Pencil className="size-3.5" /> Edit
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => setDeleting(selected)}>
                    <Trash2 className="size-3.5" /> Delete
                  </Button>
                </div>
              </div>
              <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-y border-line/70 py-3 text-xs">
                <Meta label="Category"><span className="capitalize">{selected.category}</span></Meta>
                <Meta label="Status">{selected.is_published ? "Published" : "Draft"}</Meta>
                <Meta label="Updated">{fmtDate(selected.updated_at)}</Meta>
                {selected.tags.length > 0 && (
                  <Meta label="Tags">
                    <span className="flex flex-wrap gap-1">{selected.tags.map((t) => <Badge key={t}>{t}</Badge>)}</span>
                  </Meta>
                )}
              </dl>
              <p className="mt-5 whitespace-pre-wrap text-[15px] leading-7 text-ink/90">{selected.content}</p>
            </article>
          ) : (
            <EmptyState icon={<BookOpen className="size-5" />} title={loading ? "Loading…" : "Select an article"} />
          )}
        </Card>
      </div>

      {editing && (
        <ArticleEditor
          initial={editing === "new" ? null : editing}
          adminKey={adminKey}
          onClose={() => setEditing(null)}
          onSaved={async (a) => {
            setEditing(null);
            await load();
            setSelectedId(a.id);
          }}
        />
      )}
      {deleting && (
        <Modal title="Delete this article?" onClose={() => setDeleting(null)}>
          <p className="text-sm leading-relaxed text-muted">
            “{deleting.title}” will be removed and the assistant will stop using it in answers. This can't be undone.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button onClick={() => setDeleting(null)}>Keep article</Button>
            <Button variant="primary" onClick={() => remove(deleting)}>
              <Trash2 className="size-4" /> Delete
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink">{children}</dd>
    </div>
  );
}

function ArticleEditor({ initial, adminKey, onClose, onSaved }: { initial: Article | null; adminKey: string; onClose: () => void; onSaved: (a: Article) => void }) {
  const toast = useToast();
  const start = useMemo(() => ({ ...(initial ?? EMPTY), tagText: initial?.tags.join(", ") ?? "" }), [initial]);
  const [form, setForm] = useState(start);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const dirty = (["title", "content", "category", "tagText", "is_published"] as const).some((k) => form[k] !== start[k]);

  // Unsaved-change protection, also against closing the tab.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const requestClose = () => (dirty ? setConfirmDiscard(true) : onClose());

  // Mirrors the API's limits for instant feedback; the backend still validates.
  const validate = () => {
    const e: Record<string, string> = {};
    if (form.title.trim().length < 3) e.title = "Use at least 3 characters.";
    if (form.category.trim().length < 2) e.category = "Use at least 2 characters.";
    if (form.content.trim().length < 10) e.content = "Use at least 10 characters.";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (saving || !validate()) return;
    setSaving(true);
    const body: ArticleInput = {
      title: form.title,
      content: form.content,
      category: form.category,
      is_published: form.is_published,
      tags: form.tagText.split(",").map((t) => t.trim()).filter(Boolean),
    };
    try {
      const saved = initial ? await api.updateArticle(adminKey, initial.id, body) : await api.createArticle(adminKey, body);
      toast("success", initial ? "Article updated. The assistant uses it right away." : "Article published to the knowledge base.");
      onSaved(saved);
    } catch (e) {
      toast("error", (e as ApiError).message);
    } finally {
      setSaving(false);
    }
  };

  const field = "w-full rounded-xl border border-line bg-white px-3.5 py-2.5 text-sm text-ink placeholder:text-muted/70 focus:border-hot/60 focus:outline-none focus:ring-4 focus:ring-hot/10";
  return (
    <Modal title={initial ? "Edit article" : "New article"} description="Changes are searchable by the assistant as soon as you save." onClose={requestClose} wide>
      {confirmDiscard ? (
        <div className="animate-fade-up">
          <p className="text-sm text-ink">You have unsaved changes. Discard them?</p>
          <div className="mt-5 flex justify-end gap-2">
            <Button onClick={() => setConfirmDiscard(false)}>Keep editing</Button>
            <Button variant="primary" onClick={onClose}>Discard changes</Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field label="Title" error={errors.title}>
            <input className={field} value={form.title} maxLength={200} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Category" error={errors.category}>
              <input className={field} value={form.category} maxLength={50} placeholder="billing" onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </Field>
            <Field label="Tags" hint="Comma separated">
              <input className={field} value={form.tagText} onChange={(e) => setForm({ ...form, tagText: e.target.value })} placeholder="refund, billing" />
            </Field>
          </div>
          <Field label="Content" error={errors.content} hint={`${form.content.length.toLocaleString()} / 20,000`}>
            <textarea className={`${field} min-h-56 leading-relaxed`} value={form.content} maxLength={20000} onChange={(e) => setForm({ ...form, content: e.target.value })} />
          </Field>
          <label className="flex items-center gap-2.5 text-sm text-ink">
            <input type="checkbox" checked={form.is_published} onChange={(e) => setForm({ ...form, is_published: e.target.checked })} className="size-4 accent-[var(--color-hot)]" />
            Published: visible to customers and the assistant
          </label>
          <div className="flex justify-end gap-2 border-t border-line/70 pt-4">
            <Button type="button" onClick={requestClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={saving}>
              {saving && <Spinner />} Save article
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-baseline justify-between text-xs font-medium text-ink">
        {label}
        {hint && <span className="font-normal text-muted">{hint}</span>}
      </span>
      {children}
      {error && <span className="mt-1 block text-xs text-hot" role="alert">{error}</span>}
    </label>
  );
}

export function AdminRequired({ onOpenSettings }: { onOpenSettings: () => void }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        icon={<KeyRound className="size-5" />}
        title="Admin access required"
        action={<Button variant="primary" onClick={onOpenSettings}>Open settings</Button>}
      >
        This area is for administrators. Enter a valid admin key in Settings. The server verifies it on every request.
      </EmptyState>
    </div>
  );
}
