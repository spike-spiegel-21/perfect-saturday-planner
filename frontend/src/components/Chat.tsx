import { CircleAlert, RefreshCw, Sun } from "lucide-react";
import { useEffect, useRef } from "react";
import type { OptionKind, RunOut, Simulate } from "../types";
import { AgentTrace, type TraceEntry } from "./AgentTrace";
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
  note: string | null;
}

interface Props {
  messages: ChatMessage[];
  run: RunOut | null;
  trace: TraceEntry[];
  planning: PlanningState | null;
  elapsed: number;
  choosing: OptionKind | null;
  onChoose: (kind: OptionKind) => void;
  canSimulate: boolean;
  onSimulate: (sim: Simulate) => void;
  /** Waiting for the reply to an answer: show a quiet typing indicator. */
  typing: boolean;
  /** Room to leave under the last message for the floating composer. */
  bottomSpace: number;
}

function Avatar() {
  return (
    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-accent-ink shadow-card" aria-hidden>
      <Sun size={16} strokeWidth={2.4} />
    </span>
  );
}

export function Chat({ messages, run, trace, planning, elapsed, choosing, onChoose, canSimulate, onSimulate, typing, bottomSpace }: Props) {
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
    if (planningOn || typing) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [planningOn, typing]);

  // Plans that arrive live (not on reload) -> bring the cards into view.
  useEffect(() => {
    if (!run || shownRun.current === run.run_id) return;
    const live = planningOn;
    shownRun.current = run.run_id;
    if (live) resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [run, planningOn]);

  // The agent's steps sit right under the message that kicked off the run:
  // while planning, the latest assistant message; afterwards, the one just before the plan message.
  const runIdx = run ? messages.findIndex((m) => m.runId === run.run_id) : -1;
  let anchorId: string | null = null;
  if (planning) {
    anchorId = [...messages].reverse().find((m) => m.role === "assistant" && m.tone !== "error")?.id ?? null;
  } else if (runIdx > 0 && messages[runIdx - 1].role === "assistant") {
    anchorId = messages[runIdx - 1].id;
  }

  const traceBlock =
    planning || trace.length > 0 ? (
      <div className="sm:pl-11">
        <div className="max-w-[42rem]">
          <AgentTrace
            entries={trace}
            running={planningOn}
            elapsed={planningOn ? elapsed : null}
            note={planning?.note}
            canSimulate={canSimulate}
            onSimulate={onSimulate}
          />
        </div>
      </div>
    ) : null;

  const results = run ? (
    <div ref={resultsRef} className="scroll-mt-20 sm:pl-11">
      <PlanResults run={run} onChoose={onChoose} choosing={choosing} />
    </div>
  ) : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 pt-4">
      {messages.map((m) => (
        <div key={m.id} className="animate-fade-up space-y-3">
          {m.role === "user" ? (
            <div className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-line break-words rounded-3xl rounded-tr-lg bg-cool px-4 py-2.5 text-[15px] leading-relaxed text-white shadow-card sm:max-w-[70%]">
                {m.content}
              </p>
            </div>
          ) : (
            <div className="flex items-start gap-3">
              <Avatar />
              <div
                className={[
                  "max-w-[85%] rounded-3xl rounded-tl-lg border px-4 py-2.5 text-[15px] leading-relaxed shadow-card backdrop-blur sm:max-w-[42rem]",
                  m.tone === "error" ? "border-rose/40 bg-rose-soft text-ink" : "border-line bg-surface/85 text-ink",
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
                    className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 py-1 text-sm font-medium text-ink hover:border-accent hover:text-accent"
                  >
                    <RefreshCw size={14} aria-hidden /> Try again
                  </button>
                )}
              </div>
            </div>
          )}
          {m.id === anchorId && traceBlock}
          {run && m.runId === run.run_id && (
            <>
              {!anchorId && traceBlock}
              {results}
            </>
          )}
        </div>
      ))}

      {!anchorId && runIdx < 0 && traceBlock}
      {run && runIdx < 0 && results}

      {typing && (
        <div className="flex items-start gap-3 animate-fade-up" role="status" aria-label="Reading your answer">
          <Avatar />
          <div className="rounded-3xl rounded-tl-lg border border-line bg-surface/80 px-4 py-3.5 shadow-card backdrop-blur">
            <span className="typing-dots" aria-hidden>
              <span />
              <span />
              <span />
            </span>
          </div>
        </div>
      )}

      <div style={{ height: bottomSpace }} aria-hidden />
      <div ref={endRef} />
    </div>
  );
}
