import { X } from "lucide-react";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

/* ------------------------------- buttons ------------------------------- */

type Variant = "primary" | "secondary" | "ghost" | "danger" | "white";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-white gloss hover:brightness-110",
  secondary: "bg-white text-ink border border-line shadow-soft hover:border-magenta/40 hover:text-magenta",
  ghost: "text-muted hover:bg-blush hover:text-ink",
  danger: "bg-white text-magenta border border-line hover:bg-blush",
  white: "bg-white text-berry shadow-lift hover:bg-surface",
};

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sizing = size === "sm" ? "h-9 px-3 text-[13px]" : "h-10 px-4 text-sm";
  return (
    <button
      {...props}
      className={`press inline-flex select-none items-center justify-center gap-1.5 rounded-full font-medium disabled:cursor-not-allowed disabled:opacity-50 ${sizing} ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function IconButton({ label, className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...props}
      aria-label={label}
      title={label}
      className={`press inline-flex size-9 items-center justify-center rounded-full text-muted hover:bg-blush hover:text-ink disabled:opacity-40 ${className}`}
    >
      {children}
    </button>
  );
}

/* -------------------------------- badges -------------------------------- */

type Tone = "neutral" | "pink" | "green" | "amber" | "berry";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface text-muted ring-line",
  pink: "bg-blush text-magenta ring-line",
  green: "bg-emerald-50 text-success ring-emerald-100",
  amber: "bg-amber-50 text-warning ring-amber-100",
  berry: "bg-berry text-white ring-berry",
};

export function Badge({ tone = "neutral", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

/* --------------------------------- modal --------------------------------- */

const FOCUSABLE = 'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';

/** Accessible dialog: focus trap, Escape to close, focus restored on close.
 *  A centred card on larger screens and a bottom sheet on phones. */
export function Modal({ title, description, onClose, children, wide = false }: { title: string; description?: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>("[autofocus]") ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
      if (e.key !== "Tab" || !panel.current) return;
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const [head, tail] = [items[0], items[items.length - 1]];
      if (e.shiftKey && document.activeElement === head) {
        e.preventDefault();
        tail.focus();
      } else if (!e.shiftKey && document.activeElement === tail) {
        e.preventDefault();
        head.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, []);

  return (
    <div className="animate-fade-in fixed inset-0 z-50 flex items-end justify-center bg-plum/40 sm:items-center sm:p-6" onMouseDown={onClose}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(e) => e.stopPropagation()}
        className={`animate-sheet-up sm:animate-scale-in pb-safe max-h-[92dvh] w-full overflow-y-auto rounded-t-[24px] bg-white shadow-lift sm:rounded-[24px] ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"}`}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-line/70 bg-white/95 px-6 pb-4 pt-5">
          <div className="mx-auto mb-1 h-1 w-10 rounded-full bg-line sm:hidden" aria-hidden />
          <div className="min-w-0">
            <h2 id={titleId} className="text-lg font-semibold tracking-tight text-ink">{title}</h2>
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          <IconButton label="Close" onClick={onClose} className="-mr-2 shrink-0">
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

/* ------------------------------ misc pieces ------------------------------ */

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="animate-fade-up flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-blush text-magenta ring-1 ring-line">{icon}</div>
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return <span className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${className}`} aria-hidden />;
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-[20px] border border-line/80 bg-white shadow-soft ${className}`}>{children}</div>;
}

export function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">{title}</h1>
        <p className="mt-1 max-w-xl text-sm text-muted">{description}</p>
      </div>
      {action}
    </header>
  );
}

export function Switch({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <label htmlFor={id} className="min-w-0 cursor-pointer">
        <span className="block text-sm font-medium text-ink">{label}</span>
        {description && <span className="mt-0.5 block text-xs leading-relaxed text-muted">{description}</span>}
      </label>
      <button
        id={id}
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`press relative h-7 w-12 shrink-0 rounded-full transition-colors ${checked ? "bg-brand gloss" : "bg-line"}`}
      >
        <span className={`absolute left-0 top-0.5 size-6 rounded-full bg-white shadow transition-transform duration-200 ${checked ? "translate-x-[22px]" : "translate-x-0.5"}`} />
      </button>
    </div>
  );
}

/** Brand mark: a glossy gradient tile with an abstract "A" spark. */
export function Logo({ className = "size-10" }: { className?: string }) {
  return (
    <span className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-[14px] bg-brand gloss ${className}`} aria-hidden>
      <span className="absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/30 to-transparent" />
      <svg viewBox="0 0 24 24" className="relative size-[58%] text-white" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 19 12 5l7 14" />
        <path d="M8.5 13.5h7" />
      </svg>
    </span>
  );
}
