// Mirrors backend/app/models.py — keep the two in sync.

export type Crowd = "low" | "medium" | "high";
export type VegType = "pure_veg" | "veg_friendly" | "non_veg";
export type PlaceKind = "event" | "activity" | "restaurant";
export type Energy = "low" | "medium" | "high";
export type TravelMode = "walk" | "auto" | "cab" | "metro";
export type OptionKind = "time_saver" | "recommended" | "value_for_money";
export type ValidationStatus = "pass" | "warn" | "fail";
export type SessionStatus = "collecting" | "ready" | "planning" | "planned";
export type Simulate = "weather_down" | "no_restaurants" | "llm_down";

export const KIND_ORDER: OptionKind[] = ["time_saver", "recommended", "value_for_money"];
export const KIND_LABELS: Record<OptionKind, string> = {
  time_saver: "Time Saver",
  recommended: "Recommended",
  value_for_money: "Value for Money",
};

export interface Rules {
  vegetarian: boolean;
  vegan: boolean;
  jain: boolean;
  avoid_crowds: boolean;
  no_alcohol: boolean;
  wheelchair: boolean;
  end_by: string | null;
}

export interface Slots {
  city: string | null;
  city_name: string | null;
  start_area: string | null;
  budget_inr: number | null;
  available_hours: number | null;
  start_time: string | null;
  mood: string | null;
  energy: Energy | null;
  interests: string[] | null;
  constraints: string[] | null;
  rules: Rules;
}

export interface Leg {
  from_name: string;
  to_name: string;
  mode: TravelMode;
  km: number;
  minutes: number;
  fare_inr: number;
}

export interface PlanItemOut {
  ref_id: string;
  name: string;
  kind: PlaceKind;
  label: string;
  area: string;
  start: string;
  end: string;
  duration_min: number;
  cost_inr: number;
  tier: string | null;
  indoor: boolean;
  crowd: Crowd;
  veg: VegType | null;
  blurb: string;
  why_it_fits: string;
  leg_before: Leg | null;
}

export interface Totals {
  cost_inr: number;
  spend_inr: number;
  travel_inr: number;
  activity_min: number;
  travel_min: number;
  start: string;
  end: string;
  budget_inr: number;
  available_min: number;
}

export interface Validation {
  status: ValidationStatus;
  violations: string[];
  warnings: string[];
}

export interface PlanOptionOut {
  kind: OptionKind;
  title: string;
  pitch: string;
  items: PlanItemOut[];
  leg_home: Leg | null;
  tradeoffs: string[];
  totals: Totals;
  validation: Validation;
  source: "agent" | "fallback";
}

export interface Pill {
  label: string;
  value: string;
  remembered: boolean;
}

/** How an intake turn was understood (AssistantTurn.parse). */
export interface ParseInfo {
  method?: "llm" | "rules" | string;
  ms?: number;
  updated?: string[];
  vague?: string[];
  unsupported_city?: string | null;
  [key: string]: unknown;
}

export interface AssistantTurn {
  reply: string;
  asking: string | null;
  pills: Pill[];
  multi: boolean;
  placeholder: string;
  slots: Slots;
  missing: string[];
  ready: boolean;
  parse?: ParseInfo | null;
}

export interface Usage {
  steps?: number;
  tool_calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  cost_usd?: number | null;
  seconds?: number;
}

export interface RunOut {
  run_id: string;
  options: PlanOptionOut[];
  assumptions: string[];
  weather_note: string | null;
  fallback: boolean;
  fallback_reason: string | null;
  chosen: OptionKind | null;
  usage: Usage;
}

export interface MessageOut {
  role: "user" | "assistant";
  content: string;
  turn: AssistantTurn | null;
  run_id: string | null;
}

export interface SessionOut {
  session_id: string;
  user_id: string;
  status: SessionStatus;
  slots: Slots;
  messages: MessageOut[];
  turn: AssistantTurn | null;
  last_run: RunOut | null;
  last_trace: TraceEvent[];
  memory_hint: string | null;
}

export interface MemoryOut {
  summary: string[];
  profile: Record<string, unknown> | null;
}

export interface Health {
  ok: boolean;
  model: string;
  llm_configured: boolean;
}

// --- SSE trace events (see the bottom of models.py) --------------------------------------

export type TraceEvent =
  | {
      type: "run_started";
      run_id: string;
      prefs?: Record<string, unknown>;
      window?: { start: string; end: string };
      limits?: Record<string, unknown>;
    }
  | { type: "step"; n: number; max: number }
  | { type: "narration"; text: string }
  | { type: "thinking"; text: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      name: string;
      ok: boolean;
      summary: string;
      ms: number;
      cached?: boolean;
      error?: string | null;
    }
  | {
      type: "validation";
      kind: OptionKind;
      status: ValidationStatus;
      totals?: Partial<Totals> | null;
      violations: string[];
      warnings: string[];
    }
  | { type: "guard"; name: string; detail: string }
  | { type: "fallback"; reason: string; detail?: string | null }
  | { type: "plans"; run: RunOut }
  | ({ type: "usage" } & Usage)
  | { type: "error"; message: string }
  | { type: "done" };

export type TraceEventType = TraceEvent["type"];
