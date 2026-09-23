import { Brain, ListTree, LoaderCircle, PanelRightClose, PanelRightOpen, Plus, Sun, Trash } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { MemoryOut } from "../types";

interface Props {
  traceOpen: boolean;
  onToggleTrace: () => void;
  running: boolean;
  isDesktop: boolean;
  offline: boolean;
  onNewPlan: () => void;
  loadMemory: () => Promise<MemoryOut>;
  onForget: () => Promise<void>;
}

export function Header({ traceOpen, onToggleTrace, running, isDesktop, offline, onNewPlan, loadMemory, onForget }: Props) {
  const TraceIcon = isDesktop ? (traceOpen ? PanelRightClose : PanelRightOpen) : ListTree;
  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center gap-2 border-b border-line bg-canvas/90 px-3 backdrop-blur sm:px-4">
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-ink" aria-hidden>
          <Sun size={18} strokeWidth={2.4} />
        </span>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-[15px] font-semibold text-ink">Perfect Saturday</p>
          <p className="hidden truncate text-xs text-muted sm:block">An AI agent that plans your day out</p>
        </div>
        {offline && (
          <span
            className="hidden rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn md:inline"
            title="No AI key is configured on the server, so plans come from the rule-based planner."
          >
            Offline mode
          </span>
        )}
      </div>

      <MemoryButton loadMemory={loadMemory} onForget={onForget} />

      <button
        type="button"
        onClick={onNewPlan}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
      >
        <Plus size={16} aria-hidden />
        <span className="hidden sm:inline">New plan</span>
        <span className="sr-only sm:hidden">New plan</span>
      </button>

      <button
        type="button"
        onClick={onToggleTrace}
        aria-pressed={traceOpen}
        aria-label={traceOpen ? "Hide agent trace" : "Show agent trace"}
        className="relative inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
      >
        <TraceIcon size={16} aria-hidden />
        <span className="hidden md:inline">Trace</span>
        {running && !traceOpen && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-accent" aria-hidden />}
      </button>
    </header>
  );
}

function MemoryButton({ loadMemory, onForget }: { loadMemory: () => Promise<MemoryOut>; onForget: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [memory, setMemory] = useState<MemoryOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setMemory(null);
    setError(null);
    setConfirming(false);
    loadMemory()
      .then(setMemory)
      .catch((e: Error) => setError(e.message));
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open, loadMemory]);

  const forget = async () => {
    setBusy(true);
    try {
      await onForget();
      setOpen(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
      >
        <Brain size={16} aria-hidden />
        <span className="hidden lg:inline">What I remember</span>
        <span className="sr-only lg:hidden">What I remember</span>
      </button>
      {open && (
        <div className="fixed inset-x-3 top-14 z-50 mt-1 rounded-xl border border-line bg-surface p-4 shadow-lift sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-80">
          <p className="text-sm font-semibold text-ink">What I remember about you</p>
          <p className="mt-0.5 text-xs text-muted">Stored on the server, tied to this browser. Used to suggest answers, never to fill them in.</p>
          <div className="mt-3 text-sm text-ink">
            {error ? (
              <p className="text-bad">{error}</p>
            ) : !memory ? (
              <p className="flex items-center gap-2 text-muted">
                <LoaderCircle size={14} className="animate-spin" aria-hidden /> Loading…
              </p>
            ) : memory.summary.length === 0 ? (
              <p className="text-muted">Nothing yet. After your first plan I&apos;ll remember your city, budget, constraints and the plan you pick.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-4 marker:text-faint">
                {memory.summary.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </div>
          {memory && memory.summary.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              {confirming ? (
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-muted">Forget everything and start fresh?</span>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => setConfirming(false)}
                      className="rounded-lg px-2 py-1 text-xs font-medium text-muted hover:bg-surface-2"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={forget}
                      disabled={busy}
                      className="rounded-lg bg-bad px-2 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                    >
                      {busy ? "Forgetting…" : "Yes, forget"}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-bad hover:underline"
                >
                  <Trash size={13} aria-hidden /> Forget me
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
