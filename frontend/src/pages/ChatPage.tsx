import { AlertCircle, ArrowDown, CreditCard, KeyRound, ReceiptText, RotateCcw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Composer } from "../components/Composer";
import { MessageBubble } from "../components/MessageBubble";
import { Button, Logo, Spinner } from "../components/ui";
import { useToast } from "../hooks/useToast";
import { ApiError, api } from "../services/api";
import type { Message, PendingAction, Rating } from "../types/api";

const SUGGESTIONS = [
  { label: "Check my subscription", prompt: "What is my current subscription?", icon: Sparkles },
  { label: "Reset my password", prompt: "Reset my password.", icon: KeyRound },
  { label: "Explain the refund policy", prompt: "What is your refund policy?", icon: ReceiptText },
  { label: "Help with a failed payment", prompt: "My payment failed.", icon: CreditCard },
];

interface Props {
  userId: number;
  conversationId: number | null;
  evaluationMode: boolean;
  onConversationStarted: (id: number) => void;
  onActivity: () => void;
}

export function ChatPage({ userId, conversationId, evaluationMode, onConversationStarted, onActivity }: Props) {
  const toast = useToast();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; message: string } | null>(null);
  const [input, setInput] = useState("");
  const [atBottom, setAtBottom] = useState(true);
  const justCreated = useRef<number | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setError(null);
    if (conversationId === null) {
      setMessages([]);
      setLoading(false); // a cancelled earlier load must not leave the spinner on
      return;
    }
    if (justCreated.current === conversationId) return; // we already hold its messages
    let cancelled = false;
    setLoading(true);
    api
      .conversation(userId, conversationId)
      .then((c) => {
        if (cancelled) return;
        setMessages(c.messages);
        requestAnimationFrame(() => scrollToBottom("auto"));
      })
      .catch((e: ApiError) => !cancelled && toast("error", e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [userId, conversationId, toast]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // Follow new content only when the reader is already at the bottom: never yank someone
  // who scrolled up to reread an earlier answer.
  useEffect(() => {
    if (atBottom) scrollToBottom();
  }, [messages, sending, atBottom, scrollToBottom]);

  const onScroll = () => {
    const el = scroller.current;
    if (el) setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  };

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return; // one request at a time: no duplicate submissions
    setSending(trimmed);
    setError(null);
    setInput("");
    setAtBottom(true);
    try {
      const res = await api.chat(userId, trimmed, conversationId ?? undefined);
      setMessages((m) => [...m, res.user_message, res.reply]);
      if (conversationId === null) {
        justCreated.current = res.conversation_id;
        onConversationStarted(res.conversation_id);
      }
      onActivity();
    } catch (e) {
      setError({ text: trimmed, message: (e as ApiError).message });
      setInput(trimmed);
    } finally {
      setSending(null);
      inputRef.current?.focus({ preventScroll: true });
    }
  };

  const updateAction = (action: PendingAction, followUp: Message) =>
    setMessages((ms) => [
      ...ms.map((m) => (m.actions.some((a) => a.id === action.id) ? { ...m, actions: m.actions.map((a) => (a.id === action.id ? action : a)) } : m)),
      followUp,
    ]);

  const resolve = (kind: "confirm" | "cancel") => async (id: number) => {
    try {
      const res = kind === "confirm" ? await api.confirmAction(userId, id) : await api.cancelAction(userId, id);
      setAtBottom(true);
      updateAction(res.action, res.message);
      toast(res.action.status === "confirmed" ? "success" : "error", res.message.content.slice(0, 110));
    } catch (e) {
      const err = e as ApiError;
      toast("error", err.message);
      if (err.status === 409 && conversationId) setMessages((await api.conversation(userId, conversationId)).messages); // show the real status
    }
  };

  const rate = async (id: number, rating: Rating) => {
    try {
      await api.rate(userId, id, rating);
    } catch (e) {
      toast("error", (e as ApiError).message);
      throw e;
    }
  };

  const empty = !loading && messages.length === 0 && !sending;
  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pb-6 pt-6 sm:px-6 sm:pt-10">
          {loading && <Skeleton />}
          {empty && <Welcome onPick={send} />}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} evaluationMode={evaluationMode} onRate={rate} onConfirm={resolve("confirm")} onCancel={resolve("cancel")} />
          ))}
          {sending && (
            <>
              <div className="animate-fade-up flex justify-end">
                <div className="bg-bubble gloss max-w-[86%] rounded-[22px] rounded-br-md px-4 py-2.5 text-[15px] text-white opacity-90 sm:max-w-[72%]">
                  <p className="whitespace-pre-wrap break-words">{sending}</p>
                </div>
              </div>
              <div className="animate-fade-up flex items-center gap-3" role="status">
                <Logo className="animate-glow size-8 rounded-[11px]" />
                <div className="flex items-center gap-2.5 rounded-full border border-line/80 bg-white px-4 py-2 text-sm text-muted shadow-soft">
                  <span className="flex gap-1" aria-hidden>
                    <span className="typing-dot size-1.5 rounded-full bg-hot" />
                    <span className="typing-dot size-1.5 rounded-full bg-magenta" />
                    <span className="typing-dot size-1.5 rounded-full bg-berry" />
                  </span>
                  {/* One honest stage: without streaming the client can't see which tools are running. */}
                  Understanding your request…
                </div>
              </div>
            </>
          )}
          {error && (
            <div role="alert" className="animate-fade-up flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-white p-3.5 text-sm shadow-soft">
              <AlertCircle className="size-5 shrink-0 text-hot" />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-ink">Message not sent</p>
                <p className="text-muted">{error.message}</p>
              </div>
              <Button size="sm" onClick={() => send(error.text)}>
                <RotateCcw className="size-3.5" /> Retry
              </Button>
            </div>
          )}
        </div>
      </div>

      {!atBottom && messages.length > 0 && (
        <button
          onClick={() => {
            setAtBottom(true);
            scrollToBottom();
          }}
          className="press animate-scale-in absolute bottom-28 left-1/2 z-10 -translate-x-1/2 rounded-full border border-line bg-white p-2 text-magenta shadow-lift"
          aria-label="Scroll to latest message"
        >
          <ArrowDown className="size-4" />
        </button>
      )}

      <div className="shrink-0 bg-gradient-to-t from-blush via-blush/90 to-transparent px-3 pb-3 pt-2 sm:px-6 sm:pb-4">
        <Composer value={input} onChange={setInput} onSend={() => send(input)} busy={sending !== null} inputRef={inputRef} />
      </div>
    </div>
  );
}

function Welcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="animate-fade-up flex flex-col items-center py-6 text-center sm:py-12">
      <div className="relative mb-6">
        <div className="absolute inset-0 -z-10 scale-150 rounded-full bg-hot/20 blur-2xl" aria-hidden />
        <Logo className="animate-glow size-16 rounded-[22px]" />
      </div>
      <h1 className="text-[26px] font-semibold tracking-tight text-ink sm:text-[32px]">How can I help you today?</h1>
      <p className="mt-2 max-w-md text-[15px] leading-relaxed text-muted">
        Your intelligent support assistant for subscriptions, payments, account management and more.
      </p>
      <div className="mt-8 grid w-full max-w-xl gap-2.5 sm:grid-cols-2">
        {SUGGESTIONS.map(({ label, prompt, icon: Icon }, i) => (
          <button
            key={label}
            onClick={() => onPick(prompt)}
            style={{ animationDelay: `${80 + i * 50}ms` }}
            className="press animate-fade-up group flex min-h-12 items-center gap-3 rounded-2xl border border-line/80 bg-white px-4 py-3 text-left text-sm font-medium text-ink shadow-soft transition hover:-translate-y-0.5 hover:border-hot/40 hover:shadow-lift"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-blush text-magenta ring-1 ring-line transition-colors group-hover:bg-brand group-hover:text-white group-hover:ring-transparent">
              <Icon className="size-4" />
            </span>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="flex flex-col gap-6" aria-label="Loading conversation">
      <div className="skeleton ml-auto h-10 w-2/5 rounded-[22px]" />
      <div className="flex gap-3">
        <div className="skeleton size-8 rounded-[11px]" />
        <div className="skeleton h-24 flex-1 rounded-[22px]" />
      </div>
      <span className="sr-only"><Spinner /></span>
    </div>
  );
}
