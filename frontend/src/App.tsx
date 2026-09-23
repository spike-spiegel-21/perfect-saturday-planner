import { LoaderCircle, RefreshCw, Sun } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, streamPlan } from "./api";
import { Chat, type ChatMessage, type PlanningState } from "./components/Chat";
import { Composer } from "./components/Composer";
import { FactsBar } from "./components/FactsBar";
import { Header } from "./components/Header";
import { TracePanel, type Progress, type TraceEntry } from "./components/TracePanel";
import { isComplete, newId, storage } from "./format";
import type {
  AssistantTurn,
  Health,
  MemoryOut,
  OptionKind,
  Pill,
  RunOut,
  SessionOut,
  SessionStatus,
  Simulate,
  Slots,
  TraceEvent,
} from "./types";

const USER_KEY = "ps_user_id";
const SESSION_KEY = "ps_session_id";
const SIDEBAR_KEY = "ps_trace_sidebar";
const DESKTOP = "(min-width: 1024px)";
const PLANS_INTRO = "Here are three ways to spend your Saturday. Pick one and I'll remember it for next time.";

const EMPTY_SLOTS: Slots = {
  city: null,
  city_name: null,
  start_area: null,
  budget_inr: null,
  available_hours: null,
  start_time: null,
  mood: null,
  energy: null,
  interests: null,
  constraints: null,
  rules: {
    vegetarian: false,
    vegan: false,
    jain: false,
    avoid_crowds: false,
    no_alcohol: false,
    wheelchair: false,
    end_by: null,
  },
};
const EMPTY_PROGRESS: Progress = { step: null, toolCalls: 0, costUsd: null, seconds: null };

// Offered after a plan when the backend isn't asking anything; they go through the same intake parser.
const REFINE_PILLS: Pill[] = ["Make it cheaper", "Less travel", "More outdoors", "Start later", "Swap dinner"].map((label) => ({
  label,
  value: label,
  remembered: false,
}));

// Dev-only fixture mode: ?demo=1 (finished plan) or ?demo=intake (mid-conversation). Stripped from prod builds.
const DEMO: "planned" | "intake" | null = (() => {
  if (!import.meta.env.DEV) return null;
  const v = new URLSearchParams(window.location.search).get("demo");
  return v === "1" || v === "planned" ? "planned" : v === "intake" ? "intake" : null;
})();

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    onChange();
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

function nextProgress(p: Progress, ev: TraceEvent): Progress {
  switch (ev.type) {
    case "run_started":
      return { ...EMPTY_PROGRESS };
    case "step":
      return { ...p, step: { n: ev.n, max: ev.max } };
    case "tool_call":
      return { ...p, toolCalls: p.toolCalls + 1 };
    case "usage":
      return {
        ...p,
        toolCalls: ev.tool_calls ?? p.toolCalls,
        costUsd: ev.cost_usd ?? p.costUsd,
        seconds: ev.seconds ?? p.seconds,
      };
    default:
      return p;
  }
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return e.message || "That's today's limit for planning runs on this demo. Please try again tomorrow.";
    if (e.status === 409) return "I'm already working on a plan for this chat. Hang on a moment.";
    if (e.status >= 500) return `Something went wrong on my side (${e.message}). Want to try again?`;
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export default function App() {
  const [userId] = useState(() => {
    if (DEMO) return "demo-user";
    const saved = storage.get(USER_KEY);
    if (saved) return saved;
    const id = newId();
    storage.set(USER_KEY, id);
    return id;
  });
  const isDesktop = useMediaQuery(DESKTOP);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<SessionStatus>("collecting");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [turn, setTurn] = useState<AssistantTurn | null>(null);
  const [slots, setSlots] = useState<Slots>(EMPTY_SLOTS);
  const [run, setRun] = useState<RunOut | null>(null);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [progress, setProgress] = useState<Progress>(EMPTY_PROGRESS);
  const [planning, setPlanning] = useState<PlanningState | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [sending, setSending] = useState(false);
  const [boot, setBoot] = useState<"loading" | "ready" | "error">("loading");
  const [bootError, setBootError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState<OptionKind | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => storage.get(SIDEBAR_KEY) !== "0");
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Refs for values async callbacks need without re-binding (stream handlers outlive renders).
  const sessionRef = useRef<string | null>(null);
  const runRef = useRef<RunOut | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const booted = useRef(false);
  runRef.current = run;

  const entries = (events: TraceEvent[]): TraceEntry[] =>
    events.map((ev) => ({ key: `t${seq.current++}`, at: Date.now(), ev }));
  const pushTrace = (ev: TraceEvent) => setTrace((t) => [...t, ...entries([ev])]);

  const addMessage = (msg: Omit<ChatMessage, "id">) => {
    const id = newId();
    setMessages((m) => [...m, { ...msg, id }]);
    return id;
  };
  const dropMessage = (id: string) => setMessages((m) => m.filter((x) => x.id !== id));
  const addError = (content: string, retry?: () => void) => {
    const id = newId();
    const onRetry = retry
      ? () => {
          dropMessage(id);
          retry();
        }
      : undefined;
    setMessages((m) => [...m, { id, role: "assistant", tone: "error", content, retry: onRetry }]);
  };

  const applySession = (s: SessionOut, keepTrace = false) => {
    sessionRef.current = s.session_id;
    setSessionId(s.session_id);
    if (!DEMO) storage.set(SESSION_KEY, s.session_id);
    setStatus(s.status);
    setMessages(
      s.messages.map((m, i) => ({ id: `${s.session_id}-${i}`, role: m.role, content: m.content, runId: m.run_id })),
    );
    setTurn(s.turn);
    setSlots(s.slots ?? EMPTY_SLOTS);
    setRun(s.last_run);
    if (!keepTrace) {
      const events = s.last_trace ?? [];
      setTrace(entries(events));
      setProgress(events.reduce(nextProgress, EMPTY_PROGRESS));
    }
  };

  // ------------------------------------------------------------------ planning run (SSE)

  async function startPlan(simulate: Simulate | null) {
    const sid = sessionRef.current;
    if (!sid) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let gotPlans = false;
    let gotError = false;
    let handedOff = false;

    setPlanning({ startedAt: Date.now(), lastNarration: null });
    setNow(Date.now());
    setStatus("planning");
    setProgress(EMPTY_PROGRESS);
    if (window.matchMedia(DESKTOP).matches && storage.get(SIDEBAR_KEY) !== "0") setSidebarOpen(true);

    const onEvent = (ev: TraceEvent) => {
      if (ctrl.signal.aborted) return;
      pushTrace(ev);
      setProgress((p) => nextProgress(p, ev));
      if (ev.type === "narration") {
        setPlanning((p) => (p ? { ...p, lastNarration: ev.text } : p));
      } else if (ev.type === "plans") {
        gotPlans = true;
        setRun(ev.run);
        setStatus("planned");
        setMessages((m) =>
          m.some((x) => x.runId === ev.run.run_id)
            ? m
            : [...m, { id: newId(), role: "assistant", content: PLANS_INTRO, runId: ev.run.run_id }],
        );
      } else if (ev.type === "error") {
        gotError = true;
        addError(ev.message, () => void startPlan(simulate));
      }
    };

    try {
      if (import.meta.env.DEV && DEMO) {
        const { demoRunEvents } = await import("./demo");
        for (const ev of demoRunEvents(simulate)) {
          if (ctrl.signal.aborted) return;
          await sleep(ev.type === "tool_result" ? 420 : ev.type === "thinking" ? 650 : 240);
          onEvent(ev);
        }
      } else {
        await streamPlan(sid, simulate, onEvent, ctrl.signal);
      }
      if (ctrl.signal.aborted) return;
      if (!gotPlans && !gotError) {
        addError("The planner stopped before sending any options.", () => void startPlan(simulate));
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
      if (e instanceof ApiError && e.status === 409) {
        handedOff = true;
        addMessage({ role: "assistant", content: "I'm already working on a plan for this chat. I'll show it as soon as it's ready." });
        void waitForRun(sid);
        return;
      }
      addError(errorText(e), () => void startPlan(simulate));
    } finally {
      if (!handedOff && abortRef.current === ctrl) {
        abortRef.current = null;
        setPlanning(null);
        if (!gotPlans) setStatus(runRef.current ? "planned" : "ready");
      }
    }
  }

  /** A run is already going server-side (e.g. after a reload): poll until it lands. */
  async function waitForRun(sid: string) {
    setPlanning({ startedAt: Date.now(), lastNarration: "Picking up the plan that's already in progress…" });
    setStatus("planning");
    for (let i = 0; i < 60 && sessionRef.current === sid; i++) {
      await sleep(3000);
      try {
        const s = await api.getSession(sid);
        if (s.status !== "planning") {
          if (sessionRef.current === sid) applySession(s);
          break;
        }
      } catch {
        /* keep waiting */
      }
    }
    if (sessionRef.current === sid) setPlanning(null);
  }

  // ------------------------------------------------------------------ intake turns

  async function deliver(text: string) {
    const sid = sessionRef.current;
    if (!sid) return;
    setSending(true);
    try {
      let t: AssistantTurn;
      if (import.meta.env.DEV && DEMO) {
        const { demoTurn } = await import("./demo");
        await sleep(350);
        t = demoTurn(text, slots);
      } else {
        t = await api.sendMessage(sid, text);
      }
      addMessage({ role: "assistant", content: t.reply });
      setTurn(t);
      setSlots(t.slots);
      pushTrace({ type: "parse_preferences", text, slots: t.slots, missing: t.missing, asking: t.asking, parse: t.parse ?? null });
      if (t.ready) {
        setStatus("ready");
        void startPlan(null);
      } else {
        setStatus((prev) => (t.asking ? "collecting" : prev === "planned" || runRef.current ? "planned" : "collecting"));
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        addError("This chat has expired. Start a new plan to continue.", () => void newPlan());
      } else {
        addError(errorText(e), () => void deliver(text));
      }
    } finally {
      setSending(false);
    }
  }

  function send(text: string) {
    if (!sessionRef.current || sending || planning) return;
    addMessage({ role: "user", content: text });
    void deliver(text);
  }

  // ------------------------------------------------------------------ session lifecycle

  async function bootSession() {
    setBoot("loading");
    setBootError(null);
    if (import.meta.env.DEV && DEMO) {
      const demo = await import("./demo");
      const { session, trace: demoTrace } = demo.demoSession(DEMO);
      applySession(session, true);
      setTrace(entries(demoTrace));
      setProgress(demoTrace.reduce(nextProgress, EMPTY_PROGRESS));
      setHealth({ ok: true, model: "demo", llm_configured: true });
      setBoot("ready");
      return;
    }
    api.health().then(setHealth).catch(() => setHealth(null));
    try {
      let s: SessionOut | null = null;
      const saved = storage.get(SESSION_KEY);
      if (saved) {
        try {
          s = await api.getSession(saved);
          if (s.user_id !== userId) s = null;
        } catch (e) {
          if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500) throw e;
          s = null; // 404/422: stale id -> start fresh
        }
      }
      s ??= await api.createSession(userId);
      applySession(s);
      setBoot("ready");
      if (s.status === "ready") void startPlan(null);
      else if (s.status === "planning") void waitForRun(s.session_id);
    } catch (e) {
      setBootError(errorText(e));
      setBoot("error");
    }
  }

  useEffect(() => {
    if (booted.current) return; // StrictMode runs effects twice in dev; create one session only
    booted.current = true;
    void bootSession();
  }, []);

  useEffect(() => {
    if (!planning) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [planning?.startedAt]);

  async function newPlan() {
    abortRef.current?.abort();
    abortRef.current = null;
    setPlanning(null);
    if (DEMO) {
      window.location.search = "?demo=intake";
      return;
    }
    try {
      const s = await api.createSession(userId);
      applySession(s);
    } catch (e) {
      addError(errorText(e), () => void newPlan());
    }
  }

  async function forget() {
    if (!DEMO) await api.forget(userId);
    await newPlan();
  }

  const loadMemory = useCallback(async (): Promise<MemoryOut> => {
    if (import.meta.env.DEV && DEMO) return (await import("./demo")).demoMemory;
    return api.memory(userId);
  }, [userId]);

  async function choose(kind: OptionKind) {
    const sid = sessionRef.current;
    const current = runRef.current;
    if (!sid || !current) return;
    setChoosing(kind);
    try {
      if (!DEMO) await api.choose(sid, current.run_id, kind);
      setRun((r) => (r && r.run_id === current.run_id ? { ...r, chosen: kind } : r));
    } catch (e) {
      addError(errorText(e));
    } finally {
      setChoosing(null);
    }
  }

  // ------------------------------------------------------------------ view

  const traceOpen = isDesktop ? sidebarOpen : drawerOpen;
  const toggleTrace = () => {
    if (isDesktop) {
      setSidebarOpen((o) => {
        storage.set(SIDEBAR_KEY, o ? "0" : "1");
        return !o;
      });
    } else {
      setDrawerOpen((o) => !o);
    }
  };
  const showTrace = () => (isDesktop ? setSidebarOpen(true) : setDrawerOpen(true));
  const closeTrace = () => {
    if (isDesktop) {
      storage.set(SIDEBAR_KEY, "0");
      setSidebarOpen(false);
    } else setDrawerOpen(false);
  };

  const planned = status === "planned" && !turn?.asking;
  const refine = planned && !planning && !(turn?.pills?.length ?? 0);
  const pills = planning ? [] : refine ? REFINE_PILLS : (turn?.pills ?? []);
  const placeholder = planning
    ? "Planning… you can tweak it once the options are ready."
    : planned
      ? "Want changes? e.g. make it cheaper, or start at 6pm"
      : turn?.placeholder || "Type your answer…";
  const elapsed = planning ? Math.max(0, Math.round((now - planning.startedAt) / 1000)) : 0;
  const canSimulate = isComplete(slots) && (status === "ready" || status === "planned") && !planning;

  const panel = (variant: "sidebar" | "drawer") => (
    <TracePanel
      variant={variant}
      entries={trace}
      progress={progress}
      running={Boolean(planning)}
      elapsed={planning ? elapsed : null}
      canSimulate={canSimulate}
      onSimulate={(sim) => {
        if (!isDesktop) setDrawerOpen(false);
        void startPlan(sim);
      }}
      onClose={closeTrace}
    />
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink">
      <Header
        traceOpen={traceOpen}
        onToggleTrace={toggleTrace}
        running={Boolean(planning)}
        isDesktop={isDesktop}
        offline={health != null && !health.llm_configured}
        onNewPlan={() => void newPlan()}
        loadMemory={loadMemory}
        onForget={forget}
      />

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <FactsBar slots={slots} asking={turn?.asking ?? null} />
          <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
            {boot === "loading" && (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-muted">
                <LoaderCircle size={18} className="animate-spin text-accent" aria-hidden /> Getting things ready…
              </div>
            )}
            {boot === "error" && (
              <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent-soft text-accent" aria-hidden>
                  <Sun size={22} />
                </span>
                <p className="text-sm text-muted">{bootError}</p>
                <button
                  type="button"
                  onClick={() => void bootSession()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:border-accent"
                >
                  <RefreshCw size={14} aria-hidden /> Try again
                </button>
              </div>
            )}
            {boot === "ready" && (
              <Chat
                messages={messages}
                run={run}
                planning={planning}
                elapsed={elapsed}
                choosing={choosing}
                onChoose={(k) => void choose(k)}
                onShowTrace={showTrace}
              />
            )}
          </div>
          <Composer
            pills={pills}
            multi={refine ? true : (turn?.multi ?? false)}
            placeholder={placeholder}
            disabled={boot !== "ready" || Boolean(planning)}
            busy={sending}
            onSend={send}
            turnKey={`${sessionId}:${messages.length}`}
          />
        </main>

        {isDesktop && sidebarOpen && (
          <aside className="flex w-[380px] shrink-0 flex-col border-l border-line xl:w-[420px]" aria-label="Agent trace">
            {panel("sidebar")}
          </aside>
        )}
      </div>

      {!isDesktop && drawerOpen && (
        <div className="fixed inset-0 z-40 flex flex-col justify-end" role="dialog" aria-modal="true" aria-label="Agent trace">
          <button
            type="button"
            aria-label="Close trace"
            className="absolute inset-0 bg-black/35"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative flex h-[78dvh] flex-col overflow-hidden rounded-t-2xl border-t border-line bg-surface shadow-lift animate-fade-up">
            <div className="mx-auto mb-1 mt-2 h-1 w-10 shrink-0 rounded-full bg-line-strong" aria-hidden />
            <div className="min-h-0 flex-1">{panel("drawer")}</div>
          </div>
        </div>
      )}
    </div>
  );
}
