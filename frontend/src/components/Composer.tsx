import { ArrowUp } from "lucide-react";
import { useLayoutEffect, useRef, type FormEvent } from "react";
import { Spinner } from "./ui";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  busy: boolean;
  inputRef?: React.RefObject<HTMLTextAreaElement | null>;
}

export function Composer({ value, onChange, onSend, busy, inputRef }: Props) {
  const local = useRef<HTMLTextAreaElement>(null);
  const ref = inputRef ?? local;

  // Auto-resize up to ~6 lines; re-measure when the width changes (rotation, sidebar toggle).
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const resize = () => {
      el.style.height = "auto";
      el.style.height = el.value ? `${Math.min(el.scrollHeight, 168)}px` : "";
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    return () => ro.disconnect();
  }, [value, ref]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSend();
  };

  const canSend = value.trim().length > 0 && !busy;
  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-3xl">
      <div className="flex items-end gap-2 rounded-[26px] border border-line bg-white/95 p-2 pl-4 shadow-lift transition-[border-color,box-shadow] duration-200 focus-within:border-hot/60 focus-within:shadow-[0_0_0_4px_rgb(217_8_137/0.12),var(--shadow-lift)]">
        <label htmlFor="chat-input" className="sr-only">Message</label>
        <textarea
          id="chat-input"
          ref={ref}
          rows={1}
          value={value}
          maxLength={4000}
          enterKeyHint="send"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSend) onSend();
            }
          }}
          placeholder="Ask anything about your account…"
          className="max-h-[168px] min-h-[2.5rem] flex-1 resize-none bg-transparent py-2 text-[15px] leading-relaxed text-ink placeholder:text-muted/80 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          className="press flex size-10 shrink-0 items-center justify-center rounded-full bg-brand text-white gloss disabled:opacity-40 disabled:shadow-none"
        >
          {busy ? <Spinner /> : <ArrowUp className="size-[18px]" strokeWidth={2.4} />}
        </button>
      </div>
      <p className="mt-2 hidden text-center text-[11px] text-muted sm:block">
        Enter to send · Shift + Enter for a new line · Payments and emails in this demo are simulated
      </p>
    </form>
  );
}
