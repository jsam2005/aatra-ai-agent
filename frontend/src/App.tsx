import { History, Plus, Settings2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { SettingsDialog } from "./components/SettingsDialog";
import { NAV, Sidebar, type PageId } from "./components/Sidebar";
import { Button, Logo, Modal } from "./components/ui";
import { useLocalStorage } from "./hooks/useLocalStorage";
import { useToast } from "./hooks/useToast";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ChatPage } from "./pages/ChatPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { ApiError, api } from "./services/api";
import { DEFAULT_ADMIN_KEY, DEMO_CUSTOMERS } from "./services/demo";
import type { Conversation, Health } from "./types/api";

export default function App() {
  const toast = useToast();
  const [page, setPage] = useLocalStorage<PageId>("aatra.page", "chat");
  const [userId, setUserId] = useLocalStorage<number>("aatra.user", 1);
  const [adminKey, setAdminKey] = useLocalStorage<string>("aatra.adminKey", DEFAULT_ADMIN_KEY);
  const [evaluationMode, setEvaluationMode] = useLocalStorage<boolean>("aatra.evaluationMode", false);
  const [collapsed, setCollapsed] = useLocalStorage<boolean>("aatra.sidebarCollapsed", false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deleting, setDeleting] = useState<Conversation | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => toast("error", "Cannot reach the server. Is the backend running?"));
  }, [toast]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const refreshConversations = useCallback(() => {
    api
      .conversations(userId)
      .then((p) => setConversations(p.items))
      .catch((e: ApiError) => toast("error", e.message));
  }, [userId, toast]);

  // Switching customer starts clean: their own history only (the server enforces ownership too).
  useEffect(() => {
    setConversationId(null);
    refreshConversations();
  }, [userId, refreshConversations]);

  const navigate = (p: PageId) => {
    setPage(p);
    setDrawerOpen(false);
  };
  const openConversation = (id: number | null) => {
    setConversationId(id);
    navigate("chat");
  };

  const deleteConversation = async (c: Conversation) => {
    try {
      await api.deleteConversation(userId, c.id);
      if (conversationId === c.id) setConversationId(null);
      setDeleting(null);
      refreshConversations();
      toast("success", "Conversation deleted");
    } catch (e) {
      toast("error", (e as ApiError).message);
    }
  };

  const customer = DEMO_CUSTOMERS.find((c) => c.id === userId) ?? DEMO_CUSTOMERS[0];
  const sidebarProps = {
    page,
    onNavigate: navigate,
    conversations,
    activeConversation: conversationId,
    onOpenConversation: (id: number) => openConversation(id),
    onNewConversation: () => openConversation(null),
    onDeleteConversation: setDeleting,
    customer,
    onOpenSettings: () => {
      setDrawerOpen(false);
      setSettingsOpen(true);
    },
    footerNote: (
      <p className="mt-2 px-2 text-[10.5px] leading-snug text-white/45">
        Independent demo for the Aatra AI Engineering Assignment. Nimbus is fictional.
      </p>
    ),
  };

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* Desktop: full sidebar (collapsible). Tablet: icon rail. */}
      <aside className={`hidden shrink-0 transition-[width] duration-300 ease-out md:block ${collapsed ? "w-[76px]" : "md:w-[76px] lg:w-[288px]"}`}>
        <div className="h-full lg:hidden">
          <Sidebar {...sidebarProps} collapsed onToggleCollapsed={() => setDrawerOpen(true)} />
        </div>
        <div className="hidden h-full lg:block">
          <Sidebar {...sidebarProps} collapsed={collapsed} onToggleCollapsed={() => setCollapsed((c) => !c)} />
        </div>
      </aside>

      {/* Drawer: conversation history on phones, full sidebar on tablets. */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="animate-fade-in absolute inset-0 bg-plum/45" onClick={() => setDrawerOpen(false)} />
          <div className="animate-slide-in-left absolute inset-y-0 left-0 w-[300px] max-w-[86vw] shadow-lift">
            <Sidebar {...sidebarProps} collapsed={false} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col md:p-3 md:pl-3">
        <header className="glass flex shrink-0 items-center gap-2 border-b border-line/70 px-3 py-2.5 md:hidden">
          <button onClick={() => setDrawerOpen(true)} className="press flex size-11 items-center justify-center rounded-full text-ink hover:bg-blush" aria-label="Conversation history">
            <History className="size-5" />
          </button>
          <div className="flex min-w-0 flex-1 items-center justify-center gap-2">
            <Logo className="size-7 rounded-[10px]" />
            <span className="truncate font-semibold tracking-tight">Aatra AI Agent</span>
          </div>
          <button onClick={() => openConversation(null)} className="press flex size-11 items-center justify-center rounded-full text-magenta hover:bg-blush" aria-label="New conversation">
            <Plus className="size-5" />
          </button>
        </header>

        <main className="relative min-h-0 flex-1 overflow-hidden md:rounded-[24px] md:border md:border-line/70 md:bg-surface/80 md:shadow-lift">
          <div key={page} className="animate-fade-in h-full">
            {page === "chat" && (
              <ChatPage
                key={userId}
                userId={userId}
                conversationId={conversationId}
                evaluationMode={evaluationMode}
                onConversationStarted={setConversationId}
                onActivity={refreshConversations}
              />
            )}
            {page === "kb" && <KnowledgePage adminKey={adminKey} onOpenSettings={() => setSettingsOpen(true)} />}
            {page === "analytics" && <AnalyticsPage adminKey={adminKey} onOpenSettings={() => setSettingsOpen(true)} />}
          </div>
        </main>

        {/* Phones: native-style bottom navigation with safe-area padding. */}
        <nav className="glass pb-safe shrink-0 border-t border-line/70 md:hidden" aria-label="Primary">
          <ul className="grid grid-cols-4">
            {NAV.map(({ id, label, icon: Icon }) => {
              const active = page === id;
              return (
                <li key={id}>
                  <button onClick={() => navigate(id)} aria-current={active ? "page" : undefined} className={`press flex h-16 w-full flex-col items-center justify-center gap-1 text-[11px] font-medium ${active ? "text-magenta" : "text-muted"}`}>
                    <span className={`flex h-7 w-12 items-center justify-center rounded-full transition-colors duration-200 ${active ? "bg-blush" : ""}`}>
                      <Icon className="size-5" />
                    </span>
                    {label.replace("Feedback ", "").replace("Knowledge Base", "Knowledge")}
                  </button>
                </li>
              );
            })}
            <li>
              <button onClick={() => setSettingsOpen(true)} className="press flex h-16 w-full flex-col items-center justify-center gap-1 text-[11px] font-medium text-muted">
                <span className="flex h-7 w-12 items-center justify-center rounded-full">
                  <Settings2 className="size-5" />
                </span>
                Settings
              </button>
            </li>
          </ul>
        </nav>
      </div>

      {settingsOpen && (
        <SettingsDialog
          userId={userId}
          onUserChange={setUserId}
          evaluationMode={evaluationMode}
          onEvaluationModeChange={setEvaluationMode}
          adminKey={adminKey}
          onAdminKeyChange={setAdminKey}
          health={health}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {deleting && (
        <Modal title="Delete conversation?" onClose={() => setDeleting(null)}>
          <p className="text-sm leading-relaxed text-muted">
            “{deleting.title}” and its messages, ratings and pending actions will be deleted. Support tickets are kept.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="primary" onClick={() => deleteConversation(deleting)}>
              <Trash2 className="size-4" /> Delete
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
