import { LoaderCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api, ApiError, streamPlan } from "./api";
import type { TraceEntry } from "./components/AgentTrace";
import { Chat, type ChatMessage, type PlanningState } from "./components/Chat";
import { Composer } from "./components/Composer";
import { FactsBar } from "./components/FactsBar";
import { Header, Logo } from "./components/Header";
import { Hero } from "./components/Hero";
import { isComplete, newId, storage } from "./format";
import type { AssistantTurn, Health, OptionKind, Pill, RunOut, SessionOut, SessionStatus, Simulate, Slots, TraceEvent } from "./types";

const USER_KEY = "ps_user_id";
const SESSION_KEY = "ps_session_id";
const PLANS_INTRO = "Here are three ways to spend your Saturday. Pick one and I'll remember it for next time.";
const SIM_NOTE: Record<Simulate, string> = {
  weather_down: "Re-running the plan with the weather API down, to show how the agent copes.",
  no_restaurants: "Re-running the plan with no restaurants matching, to show how the agent copes.",
  llm_down: "Re-running the plan with the AI model unavailable, to show the rule-based backup.",
};

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

/** Run a state change inside a view transition (the composer glides centre -> bottom), when supported. */
function withTransition(update: () => void) {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  if (!doc.startViewTransition || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    update();
    return;
  }
  doc.startViewTransition(() => flushSync(update));
}

/** Height of an element, kept current with a ResizeObserver. */
function useHeight(): [(el: HTMLElement | null) => void, number] {
  const [height, setHeight] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    if (!el) return;
    observer.current = new ResizeObserver(() => setHeight(el.getBoundingClientRect().height));
    observer.current.observe(el);
  }, []);
  return [ref, height];
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

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<SessionStatus>("collecting");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [turn, setTurn] = useState<AssistantTurn | null>(null);
  const [slots, setSlots] = useState<Slots>(EMPTY_SLOTS);
  const [run, setRun] = useState<RunOut | null>(null);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [planning, setPlanning] = useState<PlanningState | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [sending, setSending] = useState(false);
  const [boot, setBoot] = useState<"loading" | "ready" | "error">("loading");
  const [bootError, setBootError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState<OptionKind | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [memoryHint, setMemoryHint] = useState<string | null>(null);
  const [dockRef, dockHeight] = useHeight();

  // Refs for values async callbacks need without re-binding (stream handlers outlive renders).
  const sessionRef = useRef<string | null>(null);
  const runRef = useRef<RunOut | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const booted = useRef(false);
  runRef.current = run;

  const entries = (events: TraceEvent[]): TraceEntry[] => events.map((ev) => ({ key: `t${seq.current++}`, at: Date.now(), ev }));
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

  const applySession = (s: SessionOut) => {
    sessionRef.current = s.session_id;
    setSessionId(s.session_id);
    if (!DEMO) storage.set(SESSION_KEY, s.session_id);
    setStatus(s.status);
    setMessages(s.messages.map((m, i) => ({ id: `${s.session_id}-${i}`, role: m.role, content: m.content, runId: m.run_id })));
    setTurn(s.turn);
    setSlots(s.slots ?? EMPTY_SLOTS);
    setRun(s.last_run);
    setTrace(entries(s.last_trace ?? []));
    setMemoryHint(s.memory_hint);
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

    if (simulate) addMessage({ role: "assistant", content: SIM_NOTE[simulate] });
    setTrace([]);
    setPlanning({ startedAt: Date.now(), note: null });
    setNow(Date.now());
    setStatus("planning");

    const onEvent = (ev: TraceEvent) => {
      if (ctrl.signal.aborted) return;
      pushTrace(ev);
      if (ev.type === "plans") {
        gotPlans = true;
        setRun(ev.run);
        setStatus("planned");
        setMessages((m) =>
          m.some((x) => x.runId === ev.run.run_id) ? m : [...m, { id: newId(), role: "assistant", content: PLANS_INTRO, runId: ev.run.run_id }],
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
          await sleep(ev.type === "tool_result" ? 420 : ev.type === "thinking" ? 900 : 260);
          onEvent(ev);
        }
      } else {
        await streamPlan(sid, simulate, onEvent, ctrl.signal);
      }
      if (ctrl.signal.aborted) return;
      if (!gotPlans && !gotError) addError("The planner stopped before sending any options.", () => void startPlan(simulate));
    } catch (e) {
      if (ctrl.signal.aborted) return;
      if (e instanceof ApiError && e.status === 409) {
        handedOff = true;
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
    setPlanning({ startedAt: Date.now(), note: "Picking up the plan that's already in progress…" });
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

  const landing = boot !== "ready" || (!planning && !run && !messages.some((m) => m.role === "user"));

  function send(text: string) {
    if (!sessionRef.current || sending || planning) return;
    const add = () => addMessage({ role: "user", content: text });
    if (landing) withTransition(add);
    else add();
    void deliver(text);
  }

  // ------------------------------------------------------------------ session lifecycle

  async function bootSession() {
    setBoot("loading");
    setBootError(null);
    if (import.meta.env.DEV && DEMO) {
      const demo = await import("./demo");
      applySession(demo.demoSession(DEMO).session);
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
      withTransition(() => applySession(s));
    } catch (e) {
      addError(errorText(e), () => void newPlan());
    }
  }

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
  const offline = health != null && !health.llm_configured;

  return (
    <div className="flex h-dvh flex-col overflow-hidden text-ink">
      <Header landing={landing} offline={offline} onNewPlan={() => void newPlan()} />

      {landing ? (
        <main className="scroll-quiet flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[8vh]">
          {boot === "loading" && (
            <div className="flex flex-col items-center gap-4 text-sm text-muted">
              <Logo size={48} />
              <span className="inline-flex items-center gap-2">
                <LoaderCircle size={16} className="animate-spin text-accent" aria-hidden /> Getting things ready…
              </span>
            </div>
          )}
          {boot === "error" && (
            <div className="flex max-w-md flex-col items-center gap-4 text-center">
              <Logo size={48} />
              <p className="text-sm text-muted">{bootError}</p>
              <button
                type="button"
                onClick={() => void bootSession()}
                className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-sm font-medium hover:border-accent hover:text-accent"
              >
                <RefreshCw size={14} aria-hidden /> Try again
              </button>
            </div>
          )}
          {boot === "ready" && (
            <>
              <Hero memoryHint={memoryHint} />
              <div className="mt-9 w-full max-w-2xl">
                <Composer
                  variant="hero"
                  pills={[]}
                  multi={false}
                  placeholder={turn?.placeholder || "e.g. I'm in Gurgaon and my budget is ₹3000"}
                  disabled={false}
                  busy={sending}
                  onSend={send}
                  turnKey={`${sessionId}:hero`}
                />
              </div>
            </>
          )}
        </main>
      ) : (
        <main className="relative min-h-0 flex-1">
          <div className="scroll-quiet absolute inset-0 overflow-y-auto overflow-x-hidden">
            <FactsBar slots={slots} asking={turn?.asking ?? null} />
            <Chat
              messages={messages}
              run={run}
              trace={trace}
              planning={planning}
              elapsed={elapsed}
              choosing={choosing}
              onChoose={(k) => void choose(k)}
              canSimulate={canSimulate}
              onSimulate={(sim) => void startPlan(sim)}
              typing={sending && !planning}
              bottomSpace={dockHeight + 28}
            />
          </div>
          {/* The composer floats above the conversation instead of sitting on an opaque footer. */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-4">
            <div ref={dockRef} className="pointer-events-auto mx-auto w-full max-w-3xl">
              <Composer
                variant="dock"
                pills={pills}
                multi={refine ? true : (turn?.multi ?? false)}
                placeholder={placeholder}
                disabled={Boolean(planning)}
                busy={sending}
                onSend={send}
                turnKey={`${sessionId}:${messages.length}`}
              />
            </div>
          </div>
        </main>
      )}
    </div>
  );
}
