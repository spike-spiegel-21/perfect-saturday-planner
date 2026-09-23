import {
  Brain,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  FlaskConical,
  Flag,
  Gauge,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  Sparkles,
  TriangleAlert,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { clock, FIELD_LABEL, rupees } from "../format";
import { KIND_LABELS, type Simulate, type Slots, type TraceEvent } from "../types";

export interface TraceEntry {
  key: string;
  at: number;
  ev: TraceEvent;
}

export interface Progress {
  step: { n: number; max: number } | null;
  toolCalls: number;
  costUsd: number | null;
  seconds: number | null;
}

type ToolResult = Extract<TraceEvent, { type: "tool_result" }>;

const SIMULATIONS: { id: Simulate; label: string; detail: string }[] = [
  { id: "weather_down", label: "Weather API down", detail: "get_weather errors out; the agent has to adapt." },
  { id: "no_restaurants", label: "No restaurants match", detail: "search_restaurants returns nothing." },
  { id: "llm_down", label: "LLM unavailable", detail: "The model call fails; the rule-based planner takes over." },
];

interface Props {
  entries: TraceEntry[];
  progress: Progress;
  running: boolean;
  elapsed: number | null;
  canSimulate: boolean;
  onSimulate: (sim: Simulate) => void;
  onClose: () => void;
  variant: "sidebar" | "drawer";
}

export function TracePanel({ entries, progress, running, elapsed, canSimulate, onSimulate, onClose, variant }: Props) {
  const listRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const results = useMemo(() => {
    const map = new Map<string, ToolResult>();
    for (const { ev } of entries) if (ev.type === "tool_result") map.set(ev.id, ev);
    return map;
  }, [entries]);
  const callIds = useMemo(
    () => new Set(entries.flatMap(({ ev }) => (ev.type === "tool_call" ? [ev.id] : []))),
    [entries],
  );

  // Follow new entries while the user is at the bottom; stop following once they scroll up.
  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [entries.length, results.size]);

  const seconds = running ? elapsed : progress.seconds;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
            Agent trace
            {running && (
              <span className="relative flex h-2 w-2" aria-label="running">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
            )}
          </h2>
          <div className="flex items-center gap-1">
            <SimulateMenu disabled={!canSimulate || running} onPick={onSimulate} />
            <button
              type="button"
              onClick={onClose}
              aria-label="Close trace"
              className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink"
            >
              <X size={16} aria-hidden />
            </button>
          </div>
        </div>
        <dl className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] tabular-nums text-muted">
          <Stat label="Step" value={progress.step ? `${progress.step.n}/${progress.step.max}` : "–"} />
          <Stat label="Tools" value={String(progress.toolCalls)} />
          <Stat label="Cost" value={progress.costUsd != null ? `$${progress.costUsd.toFixed(3)}` : "–"} />
          <Stat label="Time" value={seconds != null ? `${Math.round(seconds)}s` : "–"} />
        </dl>
      </div>

      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className={`scroll-quiet min-h-0 flex-1 overflow-y-auto px-3 py-3 ${variant === "drawer" ? "pb-6" : ""}`}
      >
        {entries.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm leading-relaxed text-faint">
            Every step shows up here: how your answers were read, which tools the agent called, and how each plan was
            checked against your budget and time.
          </p>
        ) : (
          <ol className="space-y-1.5">
            {entries.map((entry) => {
              const { ev } = entry;
              if (ev.type === "done") return null;
              if (ev.type === "tool_result" && callIds.has(ev.id)) return null;
              return (
                <Entry
                  key={entry.key}
                  entry={entry}
                  result={ev.type === "tool_call" ? results.get(ev.id) : undefined}
                  running={running}
                />
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1">
      <dt>{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}

function SimulateMenu({ disabled, onPick }: { disabled: boolean; onPick: (sim: Simulate) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
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
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={disabled ? "Answer the questions first (and wait for any running plan)" : "Re-run with a simulated failure"}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-muted hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
      >
        <FlaskConical size={14} aria-hidden />
        Test failure modes
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-xl border border-line bg-surface p-1.5 shadow-lift">
          <p className="px-2 pb-1 pt-1.5 text-[11px] text-faint">Re-runs this plan with a simulated failure:</p>
          {SIMULATIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setOpen(false);
                onPick(s.id);
              }}
              className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-surface-2"
            >
              <span className="block text-sm font-medium text-ink">{s.label}</span>
              <span className="block text-xs text-muted">{s.detail}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function slotSummary(slots: Slots): string {
  const bits: string[] = [];
  if (slots.city_name ?? slots.city) bits.push(`city=${slots.city_name ?? slots.city}`);
  if (slots.budget_inr != null) bits.push(`budget=${rupees(slots.budget_inr)}`);
  if (slots.available_hours != null) bits.push(`time=${slots.available_hours}h${slots.start_time ? `@${slots.start_time}` : ""}`);
  if (slots.mood) bits.push(`mood="${slots.mood}"`);
  if (slots.interests?.length) bits.push(`interests=${slots.interests.join("/")}`);
  if (slots.constraints) bits.push(`constraints=${slots.constraints.length ? slots.constraints.join("/") : "none"}`);
  return bits.join(" · ");
}

function compactArgs(args: Record<string, unknown>): string {
  return Object.entries(args ?? {})
    .map(([k, v]) => {
      if (Array.isArray(v)) {
        if (v.length && typeof v[0] === "object" && v[0] !== null) {
          const kinds = v.map((o) => (o as { kind?: string }).kind).filter(Boolean);
          return kinds.length ? `${k}: ${kinds.join(", ")}` : `${k}: ${v.length} ${k === "legs" ? "legs" : "items"}`;
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
  children,
  raw,
  tone = "plain",
}: {
  icon: LucideIcon;
  iconClass?: string;
  spin?: boolean;
  children: ReactNode;
  raw: unknown;
  tone?: "plain" | "warn" | "bad" | "good" | "quiet";
}) {
  const [open, setOpen] = useState(false);
  const toneCls =
    tone === "warn"
      ? "border-warn/30 bg-warn-soft/60"
      : tone === "bad"
        ? "border-bad/30 bg-bad-soft/60"
        : tone === "good"
          ? "border-good/25 bg-good-soft/50"
          : tone === "quiet"
            ? "border-transparent"
            : "border-line bg-canvas/40";
  return (
    <li className={`rounded-lg border ${toneCls}`}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
        className="flex cursor-pointer items-start gap-2 px-2.5 py-2 focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Icon size={14} className={`mt-0.5 shrink-0 ${iconClass} ${spin ? "animate-spin" : ""}`} aria-hidden />
        <div className="min-w-0 flex-1 text-[13px] leading-snug text-ink">{children}</div>
        {open ? (
          <ChevronDown size={13} className="mt-0.5 shrink-0 text-faint" aria-hidden />
        ) : (
          <ChevronRight size={13} className="mt-0.5 shrink-0 text-faint" aria-hidden />
        )}
      </div>
      {open && (
        <pre className="scroll-quiet mx-2.5 mb-2.5 max-h-72 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-[11px] leading-relaxed text-muted">
          {JSON.stringify(raw, null, 2)}
        </pre>
      )}
    </li>
  );
}

function Tool({ name }: { name: string }) {
  return <span className="font-mono text-[12px] font-medium text-accent-strong">{name}</span>;
}

function Entry({ entry, result, running }: { entry: TraceEntry; result?: ToolResult; running: boolean }) {
  const { ev } = entry;
  switch (ev.type) {
    case "parse_preferences": {
      const p = ev.parse;
      const quoted = ev.text.length > 80 ? `${ev.text.slice(0, 80).trimEnd()}…` : ev.text;
      return (
        <Row icon={ListChecks} iconClass="text-info" raw={ev}>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <Tool name="parse_preferences" />
            {p?.method && (
              <span className="rounded bg-surface-2 px-1 text-[10px] font-medium uppercase text-muted">
                {p.method === "rules" ? "rules fallback" : p.method}
              </span>
            )}
            {typeof p?.ms === "number" && <span className="text-[11px] tabular-nums text-faint">{Math.round(p.ms)} ms</span>}
          </div>
          <p className="mt-0.5 break-words text-xs italic text-faint">“{quoted}”</p>
          {p?.updated && p.updated.length > 0 && (
            <p className="mt-0.5 text-xs text-muted">understood: {p.updated.map((f) => FIELD_LABEL[f] ?? f).join(", ")}</p>
          )}
          <p className="mt-0.5 break-words text-xs text-muted">{slotSummary(ev.slots) || "nothing new"}</p>
          {p?.vague && p.vague.length > 0 && (
            <p className="mt-0.5 text-xs text-warn">too vague: {p.vague.map((f) => FIELD_LABEL[f] ?? f).join(", ")} → asking again</p>
          )}
          {p?.unsupported_city && (
            <p className="mt-0.5 text-xs text-warn">no data for “{p.unsupported_city}” → offering supported cities</p>
          )}
          <p className="mt-0.5 text-xs text-faint">
            {ev.missing.length
              ? `missing: ${ev.missing.map((m) => FIELD_LABEL[m] ?? m).join(", ")}`
              : "all required fields collected → start the agent"}
          </p>
        </Row>
      );
    }
    case "run_started":
      return (
        <li className="flex items-center gap-2 px-1 pb-0.5 pt-3 text-[11px] font-semibold uppercase tracking-wide text-faint">
          <Flag size={12} aria-hidden />
          Planning run{ev.window ? ` · ${clock(ev.window.start)}–${clock(ev.window.end)}` : ""}
          <span className="h-px flex-1 bg-line" />
        </li>
      );
    case "step":
      return (
        <li className="px-1 pt-1.5 text-[11px] font-medium text-faint">
          Step {ev.n} of {ev.max}
        </li>
      );
    case "narration":
      return (
        <Row icon={MessageSquareText} iconClass="text-accent" raw={ev} tone="quiet">
          {ev.text}
        </Row>
      );
    case "thinking":
      return <Thinking text={ev.text} />;
    case "tool_call": {
      const pending = !result;
      const failed = result && (!result.ok || result.error);
      return (
        <Row
          icon={pending ? LoaderCircle : failed ? CircleX : Wrench}
          iconClass={pending ? "text-accent" : failed ? "text-bad" : "text-muted"}
          spin={pending && running}
          raw={result ? { call: ev, result } : ev}
          tone={failed ? "bad" : "plain"}
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <Tool name={ev.name} />
            {result && <span className="text-[11px] tabular-nums text-faint">{result.ms} ms</span>}
            {result?.cached && (
              <span className="rounded bg-info-soft px-1 text-[10px] font-medium uppercase text-info">cached</span>
            )}
          </div>
          {Object.keys(ev.args ?? {}).length > 0 && (
            <p className="mt-0.5 break-words font-mono text-[11px] text-faint">{compactArgs(ev.args)}</p>
          )}
          {result && (
            <p className={`mt-0.5 break-words text-xs ${failed ? "text-bad" : "text-muted"}`}>
              {result.error ? `error: ${result.error}` : result.summary}
            </p>
          )}
          {pending && !running && <p className="mt-0.5 text-xs text-faint">no result</p>}
        </Row>
      );
    }
    case "tool_result":
      // A result without a matching call (shouldn't happen, but never hide data).
      return (
        <Row icon={ev.ok ? Wrench : CircleX} iconClass={ev.ok ? "text-muted" : "text-bad"} raw={ev} tone={ev.ok ? "plain" : "bad"}>
          <Tool name={ev.name} /> <span className="text-xs text-muted">{ev.error ?? ev.summary}</span>
        </Row>
      );
    case "validation": {
      const tone = ev.status === "pass" ? "good" : ev.status === "warn" ? "warn" : "bad";
      const Icon = ev.status === "pass" ? CircleCheck : ev.status === "warn" ? TriangleAlert : CircleX;
      const iconClass = ev.status === "pass" ? "text-good" : ev.status === "warn" ? "text-warn" : "text-bad";
      const t = ev.totals;
      return (
        <Row icon={Icon} iconClass={iconClass} raw={ev} tone={tone}>
          <span className="font-medium">
            {KIND_LABELS[ev.kind] ?? ev.kind}: {ev.status}
          </span>
          {t && t.cost_inr != null && (
            <span className="text-xs text-muted">
              {" "}
              · {rupees(t.cost_inr)}
              {t.budget_inr != null ? ` / ${rupees(t.budget_inr)}` : ""}
              {t.start && t.end ? ` · ${t.start}–${t.end}` : ""}
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
        <Row icon={TriangleAlert} iconClass="text-warn" raw={ev} tone="warn">
          <span className="font-medium">Guard: {ev.name.replace(/_/g, " ")}</span>
          <p className="mt-0.5 text-xs text-muted">{ev.detail}</p>
        </Row>
      );
    case "fallback":
      return (
        <Row icon={RefreshCw} iconClass="text-warn" raw={ev} tone="warn">
          <span className="font-medium">Rule-based fallback planner</span>
          <p className="mt-0.5 text-xs text-muted">
            reason: {ev.reason.replace(/_/g, " ")}
            {ev.detail ? ` — ${ev.detail}` : ""}
          </p>
        </Row>
      );
    case "plans":
      return (
        <Row icon={Sparkles} iconClass="text-good" raw={ev.run} tone="good">
          <span className="font-medium">{ev.run.options.length} options ready</span>
          {ev.run.fallback && <span className="text-xs text-muted"> · includes fallback</span>}
        </Row>
      );
    case "usage":
      return (
        <Row icon={Gauge} iconClass="text-muted" raw={ev} tone="quiet">
          <span className="text-xs text-muted">
            Done{ev.seconds != null ? ` in ${Math.round(ev.seconds)}s` : ""}
            {ev.steps != null ? ` · ${ev.steps} steps` : ""}
            {ev.tool_calls != null ? ` · ${ev.tool_calls} tool calls` : ""}
            {ev.prompt_tokens != null ? ` · ${(ev.prompt_tokens / 1000).toFixed(1)}k in` : ""}
            {ev.completion_tokens != null ? ` / ${(ev.completion_tokens / 1000).toFixed(1)}k out` : ""}
            {ev.cost_usd != null ? ` · $${ev.cost_usd.toFixed(3)}` : ""}
          </span>
        </Row>
      );
    case "error":
      return (
        <Row icon={CircleX} iconClass="text-bad" raw={ev} tone="bad">
          {ev.message}
        </Row>
      );
    default:
      return null;
  }
}

function Thinking({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const short = text.length > 90 ? `${text.slice(0, 90).trimEnd()}…` : text;
  return (
    <li className="rounded-lg">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left"
      >
        <Brain size={14} className="mt-0.5 shrink-0 text-faint" aria-hidden />
        <span className="min-w-0 flex-1 text-xs italic leading-snug text-faint">{open ? text : short}</span>
      </button>
    </li>
  );
}
