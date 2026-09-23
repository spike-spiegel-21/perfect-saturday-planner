import type { Crowd, Slots, TravelMode, VegType } from "./types";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export const rupees = (n: number | null | undefined) => `₹${inr.format(Math.round(n ?? 0))}`;

export function minutes(total: number): string {
  const m = Math.max(0, Math.round(total));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h}h ${rest}m` : `${h}h`;
}

export function hours(h: number | null | undefined): string {
  if (h == null) return "";
  const rounded = Math.round(h * 10) / 10;
  return `${rounded} ${rounded === 1 ? "hr" : "hrs"}`;
}

/** "16:30" -> "4:30 pm" */
export function clock(hhmm: string | null | undefined): string {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const suffix = h >= 12 && h < 24 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${suffix}` : `${h12} ${suffix}`;
}

export function clockRange(start: string, end: string): string {
  const a = clock(start);
  const b = clock(end);
  // "4:30 pm – 6 pm" reads fine; drop the first suffix when both share it.
  const sa = a.slice(-2);
  const sb = b.slice(-2);
  return sa === sb ? `${a.slice(0, -3)}–${b}` : `${a} – ${b}`;
}

export const MODE_LABEL: Record<TravelMode, string> = {
  walk: "Walk",
  auto: "Auto",
  cab: "Cab",
  metro: "Metro",
};

export const CROWD_LABEL: Record<Crowd, string> = {
  low: "Quiet",
  medium: "Some crowd",
  high: "Busy",
};

export const VEG_LABEL: Record<VegType, string> = {
  pure_veg: "Pure veg",
  veg_friendly: "Veg-friendly",
  non_veg: "Non-veg",
};

export const FIELD_LABEL: Record<string, string> = {
  city: "City",
  budget: "Budget",
  available_time: "Time",
  mood: "Mood",
  interests: "Interests",
  constraints: "Constraints",
};

export function isComplete(slots: Slots | null | undefined): boolean {
  return Boolean(
    slots &&
      slots.city &&
      slots.budget_inr != null &&
      slots.available_hours != null &&
      slots.mood &&
      slots.interests &&
      slots.interests.length > 0 &&
      slots.constraints != null,
  );
}

const FALLBACK_REASONS: Record<string, string> = {
  llm_error: "the AI service didn't respond",
  llm_down: "the AI service is unavailable",
  credits: "the AI credits ran out",
  deadline: "the AI took too long",
  max_steps: "the AI ran out of steps",
  tool_budget: "the AI hit its tool-call limit",
  no_submit: "the AI didn't finish its plan",
  submit_attempts: "some AI options failed validation",
  not_configured: "no AI key is configured",
};

export function fallbackReason(reason: string | null | undefined): string {
  if (!reason) return "the AI planner couldn't finish";
  return FALLBACK_REASONS[reason] ?? reason.replace(/_/g, " ");
}

/** "Events: live from Swiggy Scenes · Places: live from Google Maps · …" */
export function sourcesLine(ds: { events: string; places: string } | null | undefined): string | null {
  if (!ds) return null;
  const events = ds.events === "swiggy" ? "live from Swiggy Scenes" : "sample data";
  const places = ds.places === "google" ? "live from Google Maps" : "sample data";
  return `Events: ${events} · Restaurants and places: ${places} · Weather, travel and crowd levels: simulated`;
}

export function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `u-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

export const storage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string | null) {
    try {
      if (value == null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch {
      /* private mode etc. — memory just won't survive a reload */
    }
  },
};
