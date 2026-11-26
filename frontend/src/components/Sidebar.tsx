import { BarChart3, BookOpen, ChevronsLeft, ChevronsRight, MessageSquare, Plus, Search, Settings2, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { dayGroup } from "../lib/format";
import type { DemoCustomer } from "../services/demo";
import { initials } from "../services/demo";
import type { Conversation } from "../types/api";
import { Logo } from "./ui";

export type PageId = "chat" | "kb" | "analytics";
export const NAV: { id: PageId; label: string; icon: typeof MessageSquare }[] = [
  { id: "chat", label: "AI Chat", icon: MessageSquare },
  { id: "kb", label: "Knowledge Base", icon: BookOpen },
  { id: "analytics", label: "Feedback Analytics", icon: BarChart3 },
];

interface Props {
  page: PageId;
  onNavigate: (p: PageId) => void;
  collapsed: boolean;
  onToggleCollapsed?: () => void;
  conversations: Conversation[];
  activeConversation: number | null;
  onOpenConversation: (id: number) => void;
  onNewConversation: () => void;
  onDeleteConversation: (c: Conversation) => void;
  customer: DemoCustomer;
  onOpenSettings: () => void;
  footerNote?: React.ReactNode;
}

export function Sidebar(p: Props) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = p.conversations.filter((c) => !q || (c.title ?? "").toLowerCase().includes(q));
    const out = new Map<string, Conversation[]>();
    filtered.forEach((c) => {
      const g = dayGroup(c.updated_at);
      out.set(g, [...(out.get(g) ?? []), c]);
    });
    return [...out.entries()];
  }, [p.conversations, query]);

  const c = p.collapsed;
  return (
    <nav aria-label="Main" className="bg-sidebar relative flex h-full flex-col overflow-hidden text-white">
      {/* soft light from the top-right corner, like a glossy surface */}
      <div className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-hot/40 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/20" aria-hidden />

      <div className={`relative flex items-center gap-3 px-4 pb-3 pt-5 ${c ? "flex-col" : ""}`}>
        <Logo className="size-10" />
        {!c && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold tracking-tight">Aatra AI Agent</p>
            <p className="truncate text-xs text-white/65">Support for Nimbus customers</p>
          </div>
        )}
        {p.onToggleCollapsed && (
          <button
            onClick={p.onToggleCollapsed}
            className="press rounded-full p-2 text-white/70 hover:bg-white/10 hover:text-white"
            aria-label={c ? "Expand sidebar" : "Collapse sidebar"}
            title={c ? "Expand sidebar" : "Collapse sidebar"}
          >
            {c ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
          </button>
        )}
      </div>

      <div className="relative px-3">
        <button
          onClick={p.onNewConversation}
          className={`press flex h-11 w-full items-center justify-center gap-2 rounded-full bg-white text-sm font-semibold text-berry shadow-lift hover:bg-surface ${c ? "px-0" : "px-4"}`}
          aria-label="New conversation"
          title="New conversation"
        >
          <Plus className="size-4" strokeWidth={2.4} />
          {!c && "New conversation"}
        </button>
      </div>

      <ul className="relative mt-4 space-y-1 px-3">
        {NAV.map(({ id, label, icon: Icon }) => {
          const active = p.page === id;
          return (
            <li key={id}>
              <button
                onClick={() => p.onNavigate(id)}
                aria-current={active ? "page" : undefined}
                title={c ? label : undefined}
                className={`press relative flex h-11 w-full items-center gap-3 rounded-2xl text-sm font-medium transition-colors ${c ? "justify-center" : "px-3.5"} ${
                  active ? "bg-white/16 text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25)] ring-1 ring-white/15" : "text-white/75 hover:bg-white/8 hover:text-white"
                }`}
              >
                {active && <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-white transition-all" aria-hidden />}
                <Icon className="size-[18px] shrink-0" />
                {!c && label}
              </button>
            </li>
          );
        })}
      </ul>

      {!c ? (
        <section className="relative mt-5 flex min-h-0 flex-1 flex-col px-3">
          <label className="relative mb-2 block">
            <span className="sr-only">Search conversations</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-white/50" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search conversations"
              className="h-9 w-full rounded-full border border-white/12 bg-white/8 pl-8 pr-3 text-[13px] text-white placeholder:text-white/45 focus:border-white/35 focus:bg-white/12 focus:outline-none"
            />
          </label>
          <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-2">
            {groups.length === 0 ? (
              <p className="px-2 py-3 text-xs text-white/55">{query ? "No matching conversations." : "Your conversations will appear here."}</p>
            ) : (
              groups.map(([label, items]) => (
                <div key={label} className="mb-3">
                  <p className="px-2 pb-1 text-[11px] font-medium text-white/50">{label}</p>
                  <ul className="space-y-0.5">
                    {items.map((conv) => {
                      const active = p.page === "chat" && p.activeConversation === conv.id;
                      return (
                        <li key={conv.id} className="group relative">
                          <button
                            onClick={() => p.onOpenConversation(conv.id)}
                            className={`press w-full truncate rounded-xl py-2 pl-3 pr-9 text-left text-[13px] transition-colors ${
                              active ? "bg-white/14 text-white" : "text-white/75 hover:bg-white/8 hover:text-white"
                            }`}
                          >
                            {conv.title || "New conversation"}
                          </button>
                          <button
                            onClick={() => p.onDeleteConversation(conv)}
                            className="press absolute right-1 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-white/55 opacity-0 hover:bg-white/10 hover:text-white focus:opacity-100 group-hover:opacity-100 max-lg:opacity-100"
                            aria-label={`Delete conversation ${conv.title ?? ""}`}
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </div>
        </section>
      ) : (
        <div className="flex-1" />
      )}

      <div className="relative border-t border-white/10 p-3">
        <button
          onClick={p.onOpenSettings}
          className={`press flex w-full items-center gap-3 rounded-2xl p-2 text-left hover:bg-white/8 ${c ? "justify-center" : ""}`}
          aria-label="Account and settings"
          title="Account and settings"
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white/15 text-xs font-semibold ring-1 ring-white/20">
            {initials(p.customer.name)}
          </span>
          {!c && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{p.customer.name}</span>
                <span className="block truncate text-xs text-white/60">{p.customer.plan} plan · demo customer</span>
              </span>
              <Settings2 className="size-4 text-white/60" />
            </>
          )}
        </button>
        {!c && p.footerNote}
      </div>
    </nav>
  );
}
