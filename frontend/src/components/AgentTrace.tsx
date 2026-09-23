import {
  Brain,
  ChevronDown,
  CircleCheck,
  CircleX,
  CloudOff,
  FlaskConical,
  MessageSquareText,
  Sparkles,
  TriangleAlert,
  Utensils,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { clock, rupees } from "../format";
import { KIND_LABELS, type Simulate, type TraceEvent } from "../types";

export interface TraceEntry {
  key: string;
  at: number;
  ev: TraceEvent;
}

type ToolResult = Extract<TraceEvent, { type: "tool_result" }>;

const TOOL_LABEL: Record<string, string> = {
  get_weather: "Checking Saturday's weather",
  search_events: "Searching events and activities",
  search_restaurants: "Finding places to eat",
  get_travel: "Working out travel times",
  validate_plan: "Checking the drafts against your budget and time",
  submit_plans: "Finalising the three options",
};

const SIMULATIONS: { id: Simulate; label: string; icon: LucideIcon }[] = [
  { id: "weather_down", label: "Weather API down", icon: CloudOff },
  { id: "no_restaurants", label: "No restaurants match", icon: Utensils },
  { id: "llm_down", label: "AI model unavailable", icon: Zap },
];

interface Props {
  entries: TraceEntry[];
  running: boolean;
  elapsed: number | null;
  note?: string | null;
  canSimulate: boolean;
  onSimulate: (sim: Simulate) => void;
}

function firstSentence(text: string): string {
  const s = text.replace(/\s+/g, " ").trim();
  const m = s.match(/^(.{20,160}?[.!?])(\s|$)/);
  return m ? m[1] : s;
}

/** The one line shown while collapsed: whatever the agent is doing right now. */
function glimpse(entries: TraceEntry[]): { key: string; text: string } | null {
  const results = new Set(entries.flatMap(({ ev }) => (ev.type === "tool_result" ? [ev.id] : [])));
  for (let i = entries.length - 1; i >= 0; i--) {
    const { key, ev } = entries[i];
    switch (ev.type) {
      case "narration":
        return { key, text: ev.text };
      case "thinking":
        return { key, text: firstSentence(ev.text) };
      case "tool_call":
        if (!results.has(ev.id)) return { key, text: `${TOOL_LABEL[ev.name] ?? ev.name}…` };
        break;
      case "validation":
        if (ev.status === "fail" && ev.violations[0]) return { key, text: `Fixing ${KIND_LABELS[ev.kind]}: ${ev.violations[0]}` };
        break;
      case "fallback":
        return { key, text: "Switching to the rule-based planner…" };
      default:
        break;
    }
  }
  return null;
}

function stats(entries: TraceEntry[]) {
  let step: { n: number; max: number } | null = null;
  let tools = 0;
  let usage: Extract<TraceEvent, { type: "usage" }> | null = null;
  let fallback: Extract<TraceEvent, { type: "fallback" }> | null = null;
  let options = 0;
  for (const { ev } of entries) {
    if (ev.type === "step") step = { n: ev.n, max: ev.max };
    else if (ev.type === "tool_call") tools += 1;
    else if (ev.type === "usage") usage = ev;
    else if (ev.type === "fallback") fallback = ev;
    else if (ev.type === "plans") options = ev.run.options.length;
  }
  return { step, tools: usage?.tool_calls ?? tools, usage, fallback, options };
}

/** Thinking + tool calls for one planning run, folded into a single line that expands. */
export function AgentTrace({ entries, running, elapsed, note, canSimulate, onSimulate }: Props) {
  const [open, setOpen] = useState(false);
  const s = useMemo(() => stats(entries), [entries]);
  const live = useMemo(() => glimpse(entries), [entries]);
  if (!running && entries.length === 0) return null;

  const seconds = running ? elapsed : s.usage?.seconds ?? null;
  const meta = [
    running && s.step ? `step ${s.step.n}/${s.step.max}` : null,
    `${s.tools} tool${s.tools === 1 ? "" : "s"}`,
    seconds != null ? `${Math.round(seconds)}s` : null,
    !running && s.usage?.cost_usd ? `$${s.usage.cost_usd.toFixed(3)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const summary = s.fallback
    ? `Rule-based backup: ${s.fallback.detail ?? s.fallback.reason}`
    : s.options
      ? `${s.options} options checked against your budget, time and constraints`
      : "Planning stopped";

  const Icon = running ? null : s.fallback ? TriangleAlert : CircleCheck;

  return (
    <div className="animate-fade-up overflow-hidden rounded-2xl border border-line bg-white/70 shadow-card backdrop-blur">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-white/60"
      >
        {running ? (
          <span className="relative flex h-6 w-6 shrink-0 items-center justify-center" aria-hidden>
            <span className="animate-orb absolute inset-0 rounded-full bg-brand opacity-80 blur-[3px]" />
            <Sparkles size={13} className="relative text-white" />
          </span>
        ) : (
          Icon && (
            <span
              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${s.fallback ? "bg-butter text-warn" : "bg-good-soft text-good"}`}
              aria-hidden
            >
              <Icon size={14} />
            </span>
          )
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-faint">
            {running ? "Agent at work" : "How I planned this"}
          </p>
          <p
            key={running ? (live?.key ?? "start") : "done"}
            className={`animate-fade-up truncate text-sm leading-snug ${running ? "shimmer font-medium" : "text-ink"}`}
            aria-live="polite"
          >
            {running ? (live?.text ?? note ?? "Getting started…") : summary}
          </p>
        </div>
        <span className="hidden shrink-0 text-xs tabular-nums text-muted sm:block">{meta}</span>
        <ChevronDown size={16} className={`shrink-0 text-faint transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>

      {open && (
        <div className="border-t border-line bg-white/50 px-3 pb-3 pt-2">
          <p className="px-1 pb-1.5 text-xs tabular-nums text-muted sm:hidden">{meta}</p>
          <TraceList entries={entries} running={running} />
          {!running && canSimulate && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line px-1 pt-3">
              <span className="mr-1 inline-flex items-center gap-1 text-xs font-medium text-muted">
                <FlaskConical size={13} aria-hidden /> Test how it copes:
              </span>
              {SIMULATIONS.map(({ id, label, icon: SimIcon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => onSimulate(id)}
                  className="inline-flex items-center gap-1 rounded-full border border-line-strong bg-white/80 px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:border-violet hover:text-violet-ink"
                >
                  <SimIcon size={12} aria-hidden /> {label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TraceList({ entries, running }: { entries: TraceEntry[]; running: boolean }) {
  const results = useMemo(() => {
    const map = new Map<string, ToolResult>();
    for (const { ev } of entries) if (ev.type === "tool_result") map.set(ev.id, ev);
    return map;
  }, [entries]);
  const callIds = useMemo(() => new Set(entries.flatMap(({ ev }) => (ev.type === "tool_call" ? [ev.id] : []))), [entries]);

  return (
    <ol className="space-y-1">
      {entries.map((entry) => {
        const { ev } = entry;
        if (ev.type === "tool_result" && callIds.has(ev.id)) return null;
        return <Entry key={entry.key} ev={ev} result={ev.type === "tool_call" ? results.get(ev.id) : undefined} running={running} />;
      })}
    </ol>
  );
}

function compactArgs(args: Record<string, unknown>): string {
  return Object.entries(args ?? {})
    .map(([k, v]) => {
      if (Array.isArray(v)) {
        if (v.length && typeof v[0] === "object" && v[0] !== null) {
          const kinds = v.map((o) => (o as { kind?: string }).kind).filter(Boolean);
          return kinds.length ? `${k}: ${kinds.join(", ")}` : `${k}: ${v.length}`;
        }
        return `${k}: ${v.join(", ")}`;
      }
      if (v && typeof v === "object") return `${k}: {…}`;
      return `${k}: ${String(v)}`;
    })
    .join(" · ");
}

function Row({
  icon: Icon,
  iconClass = "text-muted",
  spin = false,
  raw,
  children,
  tone = "plain",
}: {
  icon: LucideIcon;
  iconClass?: string;
  spin?: boolean;
  raw?: unknown;
  children: ReactNode;
  tone?: "plain" | "good" | "warn" | "bad" | "quiet";
}) {
  const [open, setOpen] = useState(false);
  const toneCls = {
    plain: "bg-white/80",
    good: "bg-good-soft/70",
    warn: "bg-butter/70",
    bad: "bg-pink-soft/80",
    quiet: "",
  }[tone];
  const expandable = raw !== undefined;
  return (
    <li className={`rounded-xl ${toneCls}`}>
      <div
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? open : undefined}
        onClick={expandable ? () => setOpen((o) => !o) : undefined}
        onKeyDown={
          expandable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setOpen((o) => !o);
                }
              }
            : undefined
        }
        className={`flex items-start gap-2 px-2.5 py-1.5 ${expandable ? "cursor-pointer" : ""}`}
      >
        <Icon size={14} className={`mt-0.5 shrink-0 ${iconClass} ${spin ? "animate-spin" : ""}`} aria-hidden />
        <div className="min-w-0 flex-1 text-[13px] leading-snug text-ink">{children}</div>
      </div>
      {open && (
        <pre className="scroll-quiet mx-2.5 mb-2 max-h-64 overflow-auto rounded-lg bg-surface-2 p-2 font-mono text-[11px] leading-relaxed text-muted">
          {JSON.stringify(raw, null, 2)}
        </pre>
      )}
    </li>
  );
}

function Entry({ ev, result, running }: { ev: TraceEvent; result?: ToolResult; running: boolean }) {
  switch (ev.type) {
    case "run_started": {
      const p = ev.prefs as Record<string, unknown> | undefined;
      const bits = p
        ? [p.city_name, p.budget_inr != null ? rupees(Number(p.budget_inr)) : null, ev.window ? `${clock(ev.window.start)}–${clock(ev.window.end)}` : null, p.mood]
            .filter(Boolean)
            .join(" · ")
        : "";
      if (!bits) return null;
      if (!bits) return null;
      return (
        <li className="px-1 pb-1 text-xs text-muted">
          <span className="font-semibold text-ink">Planning for</span> {bits}
        </li>
      );
    }
    case "step":
      return <li className="px-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">Step {ev.n}</li>;
    case "narration":
      return (
        <Row icon={MessageSquareText} iconClass="text-violet" tone="quiet">
          {ev.text}
        </Row>
      );
    case "thinking":
      return <Thinking text={ev.text} />;
    case "tool_call": {
      const failed = result && (!result.ok || result.error);
      return (
        <Row
          icon={!result ? Sparkles : failed ? CircleX : Wrench}
          iconClass={!result ? "text-orchid" : failed ? "text-bad" : "text-violet-ink"}
          spin={!result && running}
          raw={result ? { call: ev, result } : ev}
          tone={failed ? "bad" : "plain"}
        >
          <div className="flex flex-wrap items-center gap-x-2">
            <span className="font-mono text-[12px] font-semibold text-violet-ink">{ev.name}</span>
            {result && <span className="text-[11px] tabular-nums text-faint">{result.ms} ms</span>}
            {result?.cached && <span className="rounded bg-violet-soft px-1 text-[10px] font-semibold uppercase text-violet-ink">cached</span>}
          </div>
          {Object.keys(ev.args ?? {}).length > 0 && (
            <p className="mt-0.5 break-words font-mono text-[11px] text-faint">{compactArgs(ev.args)}</p>
          )}
          {result && (
            <p className={`mt-0.5 break-words text-xs ${failed ? "text-bad" : "text-muted"}`}>
              {result.error ? `error: ${result.error}` : result.summary}
            </p>
          )}
        </Row>
      );
    }
    case "tool_result":
      return (
        <Row icon={ev.ok ? Wrench : CircleX} iconClass={ev.ok ? "text-muted" : "text-bad"} raw={ev} tone={ev.ok ? "plain" : "bad"}>
          <span className="font-mono text-[12px] font-semibold">{ev.name}</span> <span className="text-xs text-muted">{ev.error ?? ev.summary}</span>
        </Row>
      );
    case "validation": {
      const tone = ev.status === "pass" ? "good" : ev.status === "warn" ? "warn" : "bad";
      const Icon = ev.status === "pass" ? CircleCheck : ev.status === "warn" ? TriangleAlert : CircleX;
      const iconClass = ev.status === "pass" ? "text-good" : ev.status === "warn" ? "text-warn" : "text-bad";
      const t = ev.totals;
      return (
        <Row icon={Icon} iconClass={iconClass} tone={tone}>
          <span className="font-medium">
            {KIND_LABELS[ev.kind] ?? ev.kind}: {ev.status}
          </span>
          {t && t.cost_inr != null && (
            <span className="text-xs text-muted">
              {" "}
              · {rupees(t.cost_inr)}
              {t.budget_inr != null ? ` of ${rupees(t.budget_inr)}` : ""}
              {t.start && t.end ? ` · ${clock(t.start)}–${clock(t.end)}` : ""}
            </span>
          )}
          {ev.violations.map((v) => (
            <p key={v} className="mt-0.5 text-xs text-bad">
              ✗ {v}
            </p>
          ))}
          {ev.warnings.map((w) => (
            <p key={w} className="mt-0.5 text-xs text-warn">
              ! {w}
            </p>
          ))}
        </Row>
      );
    }
    case "guard":
      return (
        <Row icon={TriangleAlert} iconClass="text-warn" tone="warn">
          <span className="font-medium">Guard: {ev.name.replace(/_/g, " ")}</span>
          <p className="mt-0.5 text-xs text-muted">{ev.detail}</p>
        </Row>
      );
    case "fallback":
      return (
        <Row icon={TriangleAlert} iconClass="text-warn" tone="warn">
          <span className="font-medium">Rule-based planner took over</span>
          <p className="mt-0.5 text-xs text-muted">{ev.detail ?? ev.reason}</p>
        </Row>
      );
    case "usage":
      return (
        <li className="px-1 pt-1.5 text-[11px] tabular-nums text-faint">
          Done{ev.seconds != null ? ` in ${Math.round(ev.seconds)}s` : ""}
          {ev.steps != null ? ` · ${ev.steps} steps` : ""}
          {ev.tool_calls != null ? ` · ${ev.tool_calls} tool calls` : ""}
          {ev.prompt_tokens ? ` · ${(ev.prompt_tokens / 1000).toFixed(1)}k tokens in` : ""}
          {ev.completion_tokens ? ` / ${(ev.completion_tokens / 1000).toFixed(1)}k out` : ""}
          {ev.cost_usd ? ` · $${ev.cost_usd.toFixed(3)}` : ""}
        </li>
      );
    case "error":
      return (
        <Row icon={CircleX} iconClass="text-bad" tone="bad">
          {ev.message}
        </Row>
      );
    default:
      return null;
  }
}

function Thinking({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const short = text.length > 110 ? `${text.slice(0, 110).trimEnd()}…` : text;
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 rounded-xl px-2.5 py-1.5 text-left hover:bg-white/60"
      >
        <Brain size={14} className="mt-0.5 shrink-0 text-orchid" aria-hidden />
        <span className="min-w-0 flex-1 text-xs italic leading-snug text-muted">{open ? text : short}</span>
      </button>
    </li>
  );
}
