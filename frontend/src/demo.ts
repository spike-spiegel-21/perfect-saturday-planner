// Dev-only fixture (loaded with ?demo=1 or ?demo=intake) so the UI can be checked without the backend.
// Nothing here ships: App only imports this module behind `import.meta.env.DEV`.

import type {
  AssistantTurn,
  Leg,
  PlanOptionOut,
  RunOut,
  SessionOut,
  Simulate,
  Slots,
  TraceEvent,
} from "./types";

const RULES = {
  vegetarian: false,
  vegan: false,
  jain: false,
  avoid_crowds: false,
  no_alcohol: false,
  wheelchair: false,
  end_by: null,
};

const EMPTY: Slots = {
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
  rules: RULES,
};

const S1: Slots = { ...EMPTY, city: "gurgaon", city_name: "Gurgaon", budget_inr: 3000 };
const S2: Slots = { ...S1, available_hours: 4, start_time: "16:00" };
const S3: Slots = { ...S2, mood: "tired but want some fun", energy: "low" };
const S4: Slots = { ...S3, interests: ["food", "live music", "walks"] };
const S5: Slots = {
  ...S4,
  constraints: ["vegetarian", "avoid crowded places"],
  rules: { ...RULES, vegetarian: true, avoid_crowds: true },
};

const pill = (label: string, value = label, remembered = false) => ({ label, value, remembered });

const T0: AssistantTurn = {
  reply:
    "Hey! How should we plan your Saturday? Tell me anything — where you are, your budget, how much time you have, how you're feeling.",
  asking: null,
  pills: [],
  multi: false,
  placeholder: "e.g. I'm in Gurgaon and my budget is ₹3000",
  slots: EMPTY,
  missing: ["city", "budget", "available_time", "mood", "interests", "constraints"],
  ready: false,
};
const T1: AssistantTurn = {
  reply: "Gurgaon on ₹3,000 — good start. How much time do you have on Saturday?",
  asking: "available_time",
  pills: [pill("2 hours"), pill("4 hours"), pill("Half day (6h)"), pill("Full day"), pill("Evening (5–10pm)")],
  multi: false,
  placeholder: "e.g. 4 hours from 3pm",
  slots: S1,
  missing: ["available_time", "mood", "interests", "constraints"],
  ready: false,
};
const T2: AssistantTurn = {
  reply: "4 pm to 8 pm, noted. How are you feeling going into Saturday?",
  asking: "mood",
  pills: [
    pill("Tired but want some fun"),
    pill("Chill & slow"),
    pill("Adventurous"),
    pill("Social"),
    pill("Romantic"),
    pill("Need me-time"),
  ],
  multi: true,
  placeholder: "e.g. tired but want to do something fun",
  slots: S2,
  missing: ["mood", "interests", "constraints"],
  ready: false,
};
const T3: AssistantTurn = {
  reply: "Low-key fun it is. What are you into?",
  asking: "interests",
  pills: ["Food", "Live music", "Walks", "Movies", "Art & museums", "Comedy", "Cafés", "Shopping", "Nature"].map((p) =>
    pill(p),
  ),
  multi: true,
  placeholder: "e.g. food, live music, a quiet walk",
  slots: S3,
  missing: ["interests", "constraints"],
  ready: false,
};
const T4: AssistantTurn = {
  reply: "Nice mix. Anything to avoid or keep in mind?",
  asking: "constraints",
  pills: [
    pill("Vegetarian (last time)", "Vegetarian", true),
    pill("Avoid crowds"),
    pill("No alcohol"),
    pill("Back by 9pm"),
    pill("Wheelchair-friendly"),
    pill("None"),
  ],
  multi: true,
  placeholder: 'e.g. vegetarian, avoid crowded places, or "none"',
  slots: S4,
  missing: ["constraints"],
  ready: false,
};
const T5: AssistantTurn = {
  reply: "Got everything — planning your Saturday now…",
  asking: null,
  pills: [],
  multi: false,
  placeholder: "",
  slots: S5,
  missing: [],
  ready: true,
};

const leg = (from_name: string, to_name: string, mode: Leg["mode"], km: number, minutes: number, fare_inr: number): Leg => ({
  from_name,
  to_name,
  mode,
  km,
  minutes,
  fare_inr,
});

const OPTIONS: PlanOptionOut[] = [
  {
    kind: "time_saver",
    title: "Easy evening in DLF Phase IV",
    pitch: "Two calm stops a short walk apart: one cab there, one cab back, home before 7.",
    items: [
      {
        ref_id: "gur_museo_camera",
        name: "Museo Camera",
        kind: "activity",
        label: "museum",
        area: "DLF Phase IV",
        start: "16:20",
        end: "17:35",
        duration_min: 75,
        cost_inr: 300,
        tier: "entry",
        indoor: true,
        crowd: "low",
        veg: null,
        blurb: "India's first camera museum: 3,000+ vintage cameras and rotating photo exhibitions.",
        why_it_fits: "Air-conditioned, unhurried galleries — gentle on a tired day and it skips the 32°C afternoon.",
        leg_before: leg("Cyber City", "Museo Camera", "cab", 5.2, 17, 150),
      },
      {
        ref_id: "gur_sagar_ratna_galleria",
        name: "Sagar Ratna, Galleria Market",
        kind: "restaurant",
        label: "South Indian",
        area: "DLF Phase IV",
        start: "17:45",
        end: "18:40",
        duration_min: 55,
        cost_inr: 450,
        tier: null,
        indoor: true,
        crowd: "medium",
        veg: "pure_veg",
        blurb: "Dosas, filter coffee and thalis with quick service.",
        why_it_fits: "Pure-veg comfort food an 8-minute walk away, so there's no second ride.",
        leg_before: leg("Museo Camera", "Sagar Ratna, Galleria Market", "walk", 0.6, 8, 0),
      },
    ],
    leg_home: leg("Sagar Ratna, Galleria Market", "Cyber City", "cab", 5.4, 17, 155),
    tradeoffs: [
      "No live music in this one: it trades the gig for the shortest, easiest evening.",
      "Cabs both ways cost more than an auto, but save about 15 minutes.",
    ],
    totals: {
      cost_inr: 1055,
      spend_inr: 750,
      travel_inr: 305,
      activity_min: 130,
      travel_min: 42,
      start: "16:00",
      end: "19:00",
      budget_inr: 3000,
      available_min: 240,
    },
    validation: { status: "pass", violations: [], warnings: [] },
    source: "agent",
  },
  {
    kind: "recommended",
    title: "Shaded walk, a seated gig and a slow veg dinner",
    pitch: "Eases you in outdoors, gets you live music without a club's crush, and ends with an early all-veg dinner.",
    items: [
      {
        ref_id: "gur_aravalli_park",
        name: "Aravalli Biodiversity Park",
        kind: "activity",
        label: "nature",
        area: "Sikanderpur",
        start: "16:15",
        end: "17:05",
        duration_min: 50,
        cost_inr: 0,
        tier: null,
        indoor: false,
        crowd: "low",
        veg: null,
        blurb: "Restored Aravalli scrub forest with gentle, well-marked trails.",
        why_it_fits: "Shaded trails and birdsong: an easy way to shake off a tiring week before anything else.",
        leg_before: leg("Cyber City", "Aravalli Biodiversity Park", "auto", 3.6, 12, 85),
      },
      {
        ref_id: "gur_epicentre_acoustic",
        name: "Acoustic Evenings: Unplugged Indie",
        kind: "event",
        label: "music",
        area: "Sector 44",
        start: "17:30",
        end: "18:45",
        duration_min: 75,
        cost_inr: 600,
        tier: "standard",
        indoor: true,
        crowd: "medium",
        veg: null,
        blurb: "Three indie acts, acoustic sets and auditorium seating at Epicentre.",
        why_it_fits: "Live music you can enjoy sitting down: a real gig for someone who's tired.",
        leg_before: leg("Aravalli Biodiversity Park", "Epicentre", "auto", 6.4, 22, 120),
      },
      {
        ref_id: "gur_burma_burma",
        name: "Burma Burma",
        kind: "restaurant",
        label: "Burmese",
        area: "Cyber Hub",
        start: "19:05",
        end: "19:50",
        duration_min: 45,
        cost_inr: 1100,
        tier: null,
        indoor: true,
        crowd: "medium",
        veg: "pure_veg",
        blurb: "Tea-leaf salads, khow suey and bubble tea on an entirely vegetarian menu.",
        why_it_fits: "All-vegetarian, and booked early at 7:05 pm so you get a table before it fills up.",
        leg_before: leg("Epicentre", "Burma Burma", "auto", 5.1, 18, 105),
      },
    ],
    leg_home: leg("Burma Burma", "Cyber City", "auto", 1.4, 6, 50),
    tradeoffs: [
      "The walk is outdoors at about 31°C, so it's kept to 50 minutes on the shaded trails.",
      "Three stops is the most I'd suggest on a tired day. Skip the walk if you'd rather start at the gig.",
    ],
    totals: {
      cost_inr: 2060,
      spend_inr: 1700,
      travel_inr: 360,
      activity_min: 170,
      travel_min: 58,
      start: "16:00",
      end: "19:56",
      budget_inr: 3000,
      available_min: 240,
    },
    validation: { status: "pass", violations: [], warnings: [] },
    source: "agent",
  },
  {
    kind: "value_for_money",
    title: "Park loop, a café open mic and chaat",
    pitch: "The same walk-music-food shape for about a third of the price, all around Sector 29.",
    items: [
      {
        ref_id: "gur_leisure_valley",
        name: "Leisure Valley Park",
        kind: "activity",
        label: "walk",
        area: "Sector 29",
        start: "16:15",
        end: "17:15",
        duration_min: 60,
        cost_inr: 0,
        tier: null,
        indoor: false,
        crowd: "low",
        veg: null,
        blurb: "A long, flat green belt with a shaded inner loop.",
        why_it_fits: "A flat, green loop: a walk that doesn't ask much of tired legs.",
        leg_before: leg("Cyber City", "Leisure Valley Park", "auto", 4.3, 15, 90),
      },
      {
        ref_id: "gur_open_mic_29",
        name: "Sundowner Open Mic",
        kind: "event",
        label: "music",
        area: "Sector 29",
        start: "17:30",
        end: "18:30",
        duration_min: 60,
        cost_inr: 200,
        tier: "cover",
        indoor: true,
        crowd: "medium",
        veg: null,
        blurb: "Acoustic sets from local musicians in a small café; cover redeemable on food.",
        why_it_fits: "Live acoustic music for the price of a coffee: your cheapest music fix.",
        leg_before: leg("Leisure Valley Park", "Sundowner Open Mic", "walk", 0.9, 12, 0),
      },
      {
        ref_id: "gur_haldirams_29",
        name: "Haldiram's, Sector 29",
        kind: "restaurant",
        label: "North Indian & chaat",
        area: "Sector 29",
        start: "18:35",
        end: "19:20",
        duration_min: 45,
        cost_inr: 350,
        tier: null,
        indoor: true,
        crowd: "medium",
        veg: "pure_veg",
        blurb: "Chaat, thalis and sweets; fast and reliable.",
        why_it_fits: "Pure-veg chaat and a thali, quick and filling, right next door.",
        leg_before: leg("Sundowner Open Mic", "Haldiram's, Sector 29", "walk", 0.4, 5, 0),
      },
    ],
    leg_home: leg("Haldiram's, Sector 29", "Cyber City", "auto", 4.6, 16, 95),
    tradeoffs: [
      "An open mic is hit-or-miss next to a curated gig, but it costs ₹200 instead of ₹600.",
      "The park is outdoors at 32°C at 4 pm; stick to the shaded inner loop.",
    ],
    totals: {
      cost_inr: 735,
      spend_inr: 550,
      travel_inr: 185,
      activity_min: 165,
      travel_min: 48,
      start: "16:00",
      end: "19:36",
      budget_inr: 3000,
      available_min: 240,
    },
    validation: {
      status: "warn",
      violations: [],
      warnings: ["Leisure Valley Park is outdoors at 16:00 (32°C, humid)."],
    },
    source: "agent",
  },
];

export const demoRun: RunOut = {
  run_id: "run_demo",
  options: OPTIONS,
  assumptions: [
    "Starting from Cyber City. Tell me your area for tighter travel times.",
    "You're free 4–8 pm, including the ride back.",
    "Budget is for one person: tickets, food and travel.",
  ],
  weather_note: "Saturday in Gurgaon: 32°C and humid at 4 pm, easing to 28°C by 7 pm. Rain unlikely (≤20%), AQI moderate (~150).",
  fallback: false,
  fallback_reason: null,
  chosen: null,
  usage: { steps: 5, tool_calls: 7, prompt_tokens: 52340, completion_tokens: 4420, cost_usd: 0.071, seconds: 41.6 },
};

const kinds = (...k: string[]) => ({ options: k.map((kind) => ({ kind })) });

function runTrace(simulate: Simulate | null, run: RunOut): TraceEvent[] {
  const [ts, rec, val] = run.options;
  if (simulate === "llm_down") {
    return [
      { type: "run_started", run_id: run.run_id, window: { start: "16:00", end: "20:00" }, limits: { max_steps: 8 } },
      { type: "step", n: 1, max: 8 },
      { type: "guard", name: "llm_error", detail: "Model call failed: service unavailable (simulated)." },
      { type: "fallback", reason: "llm_error", detail: "Building all three options with the rule-based planner." },
      { type: "validation", kind: "time_saver", status: ts.validation.status, totals: ts.totals, violations: [], warnings: ts.validation.warnings },
      { type: "validation", kind: "recommended", status: rec.validation.status, totals: rec.totals, violations: [], warnings: rec.validation.warnings },
      { type: "validation", kind: "value_for_money", status: val.validation.status, totals: val.totals, violations: [], warnings: val.validation.warnings },
      { type: "plans", run },
      { type: "usage", steps: 1, tool_calls: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0, seconds: 1.2 },
      { type: "done" },
    ];
  }
  const weatherDown = simulate === "weather_down";
  const noFood = simulate === "no_restaurants";
  return [
    { type: "run_started", run_id: run.run_id, window: { start: "16:00", end: "20:00" }, limits: { max_steps: 8, max_tool_calls: 40 } },
    { type: "step", n: 1, max: 8 },
    { type: "narration", text: "Checking Saturday's weather and looking for low-key music, walks and veg food near Cyber City." },
    { type: "tool_call", id: "c1", name: "get_weather", args: { city: "gurgaon" } },
    { type: "tool_call", id: "c2", name: "search_events", args: { categories: ["music", "walk", "nature", "food_walk"], max_price: 1500 } },
    { type: "tool_call", id: "c3", name: "search_restaurants", args: { max_cost_for_one: 1200, veg_only: true, avoid_crowds: true } },
    weatherDown
      ? { type: "tool_result", id: "c1", name: "get_weather", ok: false, summary: "", ms: 5002, error: "weather service unavailable (simulated)" }
      : { type: "tool_result", id: "c1", name: "get_weather", ok: true, summary: "32°C at 16:00 → 28°C by 19:00 · rain ≤20% · AQI ~150", ms: 2 },
    { type: "tool_result", id: "c2", name: "search_events", ok: true, summary: "6 matches + 5 cheaper alternatives · 3 hidden (crowded in your window)", ms: 4 },
    noFood
      ? { type: "tool_result", id: "c3", name: "search_restaurants", ok: true, summary: "0 places matched (simulated)", ms: 3 }
      : { type: "tool_result", id: "c3", name: "search_restaurants", ok: true, summary: "6 veg places + 4 cheaper alternatives · 2 hidden (busy at dinner)", ms: 3 },
    { type: "step", n: 2, max: 8 },
    {
      type: "thinking",
      text: "Tired + avoid crowds → at most 3 stops, something seated after the walk. The 17:30 acoustic set at Epicentre fits between a park walk and an early dinner; Sector 29 has a free-ish version of the same evening.",
    },
    {
      type: "narration",
      text: weatherDown
        ? "Weather is unavailable, so I'll keep outdoor time short and have indoor backups."
        : noFood
          ? "No restaurants matched, so I'll plan around snack-friendly venues and say so."
          : "Drafting three options and checking travel times between the stops.",
    },
    { type: "tool_call", id: "c4", name: "get_travel", args: { legs: new Array(6).fill({}) } },
    { type: "tool_result", id: "c4", name: "get_travel", ok: true, summary: "6 legs · 0.4–6.4 km · walk, auto, cab", ms: 1 },
    { type: "step", n: 3, max: 8 },
    { type: "narration", text: "Validating all three drafts against your ₹3,000 budget and 4–8 pm window." },
    { type: "tool_call", id: "c5", name: "validate_plan", args: kinds("time_saver", "recommended", "value_for_money") },
    { type: "tool_result", id: "c5", name: "validate_plan", ok: true, summary: "time_saver pass · recommended fail · value_for_money warn", ms: 2 },
    { type: "validation", kind: "time_saver", status: "pass", totals: ts.totals, violations: [], warnings: [] },
    {
      type: "validation",
      kind: "recommended",
      status: "fail",
      totals: { ...rec.totals, end: "20:25" },
      violations: ["Ends at 20:25 — 25 min past your 20:00 window (including the ride back)."],
      warnings: [],
    },
    { type: "validation", kind: "value_for_money", status: "warn", totals: val.totals, violations: [], warnings: val.validation.warnings },
    { type: "step", n: 4, max: 8 },
    { type: "narration", text: "Shortening dinner to 45 minutes so the recommended plan gets you home by 8, then re-checking." },
    { type: "tool_call", id: "c6", name: "validate_plan", args: kinds("recommended") },
    { type: "tool_result", id: "c6", name: "validate_plan", ok: true, summary: "recommended pass", ms: 1 },
    { type: "validation", kind: "recommended", status: "pass", totals: rec.totals, violations: [], warnings: [] },
    { type: "step", n: 5, max: 8 },
    { type: "tool_call", id: "c7", name: "submit_plans", args: kinds("time_saver", "recommended", "value_for_money") },
    { type: "tool_result", id: "c7", name: "submit_plans", ok: true, summary: "accepted · 3 options", ms: 3 },
    { type: "plans", run },
    { type: "usage", ...run.usage },
    { type: "done" },
  ];
}

const fallbackRun: RunOut = {
  ...demoRun,
  run_id: "run_demo_fallback",
  fallback: true,
  fallback_reason: "llm_error",
  options: demoRun.options.map((o) => ({ ...o, source: "fallback" as const })),
  usage: { steps: 1, tool_calls: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0, seconds: 1.2 },
};

/** Events for a replayed demo run (what the SSE stream would send). */
export function demoRunEvents(simulate: Simulate | null): TraceEvent[] {
  if (simulate === "llm_down") return runTrace(simulate, fallbackRun);
  const run: RunOut = { ...demoRun, run_id: `run_demo_${Date.now().toString(36)}` };
  return runTrace(simulate, run);
}

const msg = (role: "user" | "assistant", content: string, turn: AssistantTurn | null = null, run_id: string | null = null) => ({
  role,
  content,
  turn,
  run_id,
});

const conversation = [
  msg("assistant", T0.reply, T0),
  msg("user", "i am at gurgaon, and my budget is ₹3000"),
  msg("assistant", T1.reply, T1),
  msg("user", "4 hours from 4pm"),
  msg("assistant", T2.reply, T2),
  msg("user", "Tired but want some fun"),
  msg("assistant", T3.reply, T3),
  msg("user", "Food, Live music, Walks"),
  msg("assistant", T4.reply, T4),
];

export function demoSession(mode: "planned" | "intake"): { session: SessionOut } {
  if (mode === "intake") {
    return {
      session: {
        session_id: "demo",
        user_id: "demo-user",
        status: "collecting",
        slots: S4,
        messages: conversation,
        turn: T4,
        last_run: null,
        last_trace: [],
        memory_hint: "Last time: Gurgaon · ₹3,000 · vegetarian",
      },
    };
  }
  return {
    session: {
      session_id: "demo",
      user_id: "demo-user",
      status: "planned",
      slots: S5,
      messages: [
        ...conversation,
        msg("user", "Vegetarian, Avoid crowds"),
        msg("assistant", T5.reply, T5),
        msg("assistant", "Here are three ways to spend your Saturday. Pick one and I'll remember it for next time.", null, "run_demo"),
      ],
      turn: T5,
      last_run: demoRun,
      last_trace: runTrace(null, demoRun),
      memory_hint: null,
    },
  };
}

/** Stand-in for POST /messages in demo mode: finishing the intake starts a replayed run. */
export function demoTurn(text: string, slots: Slots): AssistantTurn {
  if (slots.constraints == null) {
    const parts = text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const none = parts.length === 1 && /^(none|no constraints|nothing)$/i.test(parts[0]);
    const lower = parts.map((p) => p.toLowerCase());
    const filled: Slots = {
      ...slots,
      constraints: none ? [] : parts,
      rules: {
        ...slots.rules,
        vegetarian: lower.some((p) => p.includes("veg")),
        avoid_crowds: lower.some((p) => p.includes("crowd")),
        no_alcohol: lower.some((p) => p.includes("alcohol")),
        wheelchair: lower.some((p) => p.includes("wheelchair")),
      },
    };
    return { ...T5, slots: filled, parse: { method: "rules", ms: 1, updated: ["constraints"], vague: [] } };
  }
  return {
    reply: "This is demo mode, so I can't re-plan from text. Open “How I planned this” above the cards to replay a run with a simulated failure.",
    asking: null,
    pills: [],
    multi: false,
    placeholder: "",
    slots,
    missing: [],
    ready: false,
    parse: { method: "rules", ms: 0, updated: [], vague: [] },
  };
}
