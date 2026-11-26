import { BookOpen, Check, ChevronDown, Copy, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState, type ReactNode } from "react";
import { fmtTime } from "../lib/format";
import type { Message, Rating } from "../types/api";
import { ActionCard } from "./ActionCard";
import { Markdown } from "./Markdown";
import { ResponseCards } from "./ResponseCards";
import { TracePanel } from "./TracePanel";
import { Badge, Logo } from "./ui";

interface Props {
  message: Message;
  evaluationMode: boolean;
  onRate: (id: number, rating: Rating) => Promise<void>;
  onConfirm: (id: number) => Promise<void>;
  onCancel: (id: number) => Promise<void>;
}

export function MessageBubble({ message, evaluationMode, onRate, onConfirm, onCancel }: Props) {
  const [showTrace, setShowTrace] = useState(false);
  const [rating, setRating] = useState<Rating | null>(message.feedback?.rating ?? null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    return (
      <div className="animate-fade-up flex justify-end">
        <div className="max-w-[86%] sm:max-w-[72%]">
          <div className="bg-bubble gloss rounded-[22px] rounded-br-md px-4 py-2.5 text-[15px] leading-relaxed text-white">
            {/* React escapes text: user input is never rendered as HTML. */}
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          </div>
          <p className="mt-1 pr-1 text-right text-[11px] text-muted">{fmtTime(message.created_at)}</p>
        </div>
      </div>
    );
  }

  const rate = async (r: Rating) => {
    if (ratingBusy || rating === r) return;
    setRatingBusy(true);
    try {
      await onRate(message.id, r);
      setRating(r);
    } finally {
      setRatingBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (insecure context); nothing to do */
    }
  };

  const system = message.provider === "system";
  return (
    <div className="animate-fade-up flex gap-3">
      <Logo className="mt-0.5 size-8 rounded-[11px]" />
      <div className="min-w-0 max-w-[calc(100%-2.75rem)] flex-1 sm:max-w-[80%]">
        <div className="rounded-[22px] rounded-tl-md border border-line/80 bg-white px-4 py-3 shadow-soft">
          <Markdown>{message.content}</Markdown>
          <ResponseCards cards={message.cards} />
          {message.actions.map((a) => (
            <ActionCard key={a.id} action={a} onConfirm={onConfirm} onCancel={onCancel} />
          ))}
          {message.citations.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line/60 pt-2.5">
              <span className="text-xs text-muted">Sources</span>
              {message.citations.map((c) => (
                <Badge key={c.id} tone="pink">
                  <BookOpen className="size-3" /> {c.title}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-0.5 px-1 text-[11px] text-muted">
          <span className="mr-1.5">{fmtTime(message.created_at)}</span>
          {!system && (
            <>
              <Action label={copied ? "Copied" : "Copy answer"} onClick={copy}>
                {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
              </Action>
              <Action label="Helpful" pressed={rating === "up"} disabled={ratingBusy} onClick={() => rate("up")}>
                <ThumbsUp className="size-3.5" />
              </Action>
              <Action label="Not helpful" pressed={rating === "down"} disabled={ratingBusy} onClick={() => rate("down")}>
                <ThumbsDown className="size-3.5" />
              </Action>
              {evaluationMode && (
                <button
                  onClick={() => setShowTrace((s) => !s)}
                  aria-expanded={showTrace}
                  className="press ml-1 inline-flex items-center gap-0.5 rounded-full px-2 py-1 hover:bg-blush hover:text-ink"
                >
                  Details <ChevronDown className={`size-3 transition-transform duration-200 ${showTrace ? "rotate-180" : ""}`} />
                </button>
              )}
            </>
          )}
        </div>
        {evaluationMode && showTrace && <TracePanel message={message} />}
      </div>
    </div>
  );
}

function Action({ label, pressed, disabled, onClick, children }: { label: string; pressed?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={`press inline-flex size-8 items-center justify-center rounded-full ${pressed ? "bg-blush text-magenta" : "hover:bg-blush hover:text-ink"}`}
    >
      {children}
    </button>
  );
}
