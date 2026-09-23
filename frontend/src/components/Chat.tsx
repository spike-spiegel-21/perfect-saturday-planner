import { CircleAlert, ListTree, LoaderCircle, RefreshCw, Sun } from "lucide-react";
import { useEffect, useRef } from "react";
import type { OptionKind, RunOut } from "../types";
import { PlanResults } from "./PlanCards";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  runId?: string | null;
  tone?: "normal" | "error";
  retry?: () => void;
}

export interface PlanningState {
  startedAt: number;
  lastNarration: string | null;
}

interface Props {
  messages: ChatMessage[];
  run: RunOut | null;
  planning: PlanningState | null;
  elapsed: number;
  choosing: OptionKind | null;
  onChoose: (kind: OptionKind) => void;
  onShowTrace: () => void;
}

function Avatar() {
  return (
    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent" aria-hidden>
      <Sun size={17} strokeWidth={2.2} />
    </span>
  );
}

export function Chat({ messages, run, planning, elapsed, choosing, onChoose, onShowTrace }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const shownRun = useRef<string | null>(null);
  const planningOn = planning != null;
  const last = messages[messages.length - 1];

  // New message -> keep it in view; a message that carries plans -> show the top of the cards.
  useEffect(() => {
    if (last?.runId) resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    else endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  useEffect(() => {
    if (planningOn) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [planningOn]);

  // Plans that arrive live (not on reload) -> bring the cards into view.
  useEffect(() => {
    if (!run || shownRun.current === run.run_id) return;
    const live = planningOn;
    shownRun.current = run.run_id;
    if (live) resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [run, planningOn]);

  const anchored = run ? messages.some((m) => m.runId === run.run_id) : false;

  const results = run ? (
    <div ref={resultsRef} className="scroll-mt-4 pl-0 sm:pl-11">
      <PlanResults run={run} onChoose={onChoose} choosing={choosing} />
    </div>
  ) : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6">
      {messages.map((m) => (
        <div key={m.id} className="animate-fade-up space-y-3">
          {m.role === "user" ? (
            <div className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-line break-words rounded-2xl rounded-tr-md border border-accent/20 bg-accent-soft px-4 py-2.5 text-[15px] leading-relaxed text-ink sm:max-w-[70%]">
                {m.content}
              </p>
            </div>
          ) : (
            <div className="flex items-start gap-3">
              <Avatar />
              <div
                className={[
                  "max-w-[85%] rounded-2xl rounded-tl-md border px-4 py-2.5 text-[15px] leading-relaxed shadow-card sm:max-w-[42rem]",
                  m.tone === "error" ? "border-bad/30 bg-bad-soft text-ink" : "border-line bg-surface text-ink",
                ].join(" ")}
              >
                <p className="flex items-start gap-2 whitespace-pre-line break-words">
                  {m.tone === "error" && <CircleAlert size={17} className="mt-1 shrink-0 text-bad" aria-hidden />}
                  <span>{m.content}</span>
                </p>
                {m.retry && (
                  <button
                    type="button"
                    onClick={m.retry}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1 text-sm font-medium text-ink hover:border-accent hover:text-accent-strong"
                  >
                    <RefreshCw size={14} aria-hidden /> Try again
                  </button>
                )}
              </div>
            </div>
          )}
          {run && m.runId === run.run_id && results}
        </div>
      ))}

      {run && !anchored && results}

      {planning && (
        <div className="flex items-start gap-3 animate-fade-up" aria-live="polite">
          <Avatar />
          <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3 shadow-card sm:max-w-[42rem]">
            <p className="flex items-center gap-2 text-[15px] font-medium text-ink">
              <LoaderCircle size={17} className="animate-spin text-accent" aria-hidden />
              Planning your Saturday…
              <span className="text-sm font-normal tabular-nums text-faint">{elapsed}s</span>
            </p>
            <p className="mt-1 text-sm leading-snug text-muted">
              {planning.lastNarration ?? "Checking weather, events, food and travel, then validating three options."}
            </p>
            <button
              type="button"
              onClick={onShowTrace}
              className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-accent-strong hover:underline"
            >
              <ListTree size={15} aria-hidden /> Watch the agent work
            </button>
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
