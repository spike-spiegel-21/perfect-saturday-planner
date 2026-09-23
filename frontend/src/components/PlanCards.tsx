import {
  Car,
  CarTaxiFront,
  Check,
  ChevronDown,
  CircleCheck,
  CircleX,
  CloudSun,
  Footprints,
  House,
  Info,
  Leaf,
  LoaderCircle,
  PiggyBank,
  Scale,
  Sparkles,
  Ticket,
  TrainFront,
  Trees,
  TriangleAlert,
  Users,
  UtensilsCrossed,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { clock, clockRange, CROWD_LABEL, fallbackReason, minutes, MODE_LABEL, rupees, VEG_LABEL } from "../format";
import { KIND_LABELS, KIND_ORDER, type Leg, type OptionKind, type PlanItemOut, type PlanOptionOut, type RunOut } from "../types";

const KIND_STYLE: Record<OptionKind, { icon: LucideIcon; text: string; soft: string; dot: string }> = {
  time_saver: { icon: Zap, text: "text-violet-ink", soft: "bg-violet-soft", dot: "bg-violet" },
  recommended: { icon: Sparkles, text: "text-orchid-ink", soft: "bg-orchid-soft", dot: "bg-orchid" },
  value_for_money: { icon: PiggyBank, text: "text-pink-ink", soft: "bg-pink-soft", dot: "bg-pink" },
};

const MODE_ICON: Record<Leg["mode"], LucideIcon> = {
  walk: Footprints,
  auto: CarTaxiFront,
  cab: Car,
  metro: TrainFront,
};

interface Props {
  run: RunOut;
  onChoose: (kind: OptionKind) => void;
  choosing: OptionKind | null;
}

export function PlanResults({ run, onChoose, choosing }: Props) {
  const byKind = new Map(run.options.map((o) => [o.kind, o]));
  const options = KIND_ORDER.map((k) => byKind.get(k)).filter((o): o is PlanOptionOut => Boolean(o));

  return (
    <section className="animate-fade-up space-y-3" aria-label="Your Saturday options">
      {run.fallback && (
        <p className="flex items-start gap-2 rounded-xl bg-butter/80 px-3.5 py-2 text-sm text-ink">
          <TriangleAlert size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          <span>
            <span className="font-medium">Rule-based plan</span>
            <span className="text-muted"> · {fallbackReason(run.fallback_reason)}. Same data, same budget and time checks.</span>
          </span>
        </p>
      )}

      <Notes run={run} />

      <div className="@container">
        <div className="grid grid-cols-1 gap-4 pt-1 @3xl:grid-cols-3 @3xl:items-start @3xl:pt-4">
          {options.map((option) => (
            <PlanCard
              key={`${run.run_id}-${option.kind}`}
              option={option}
              chosen={run.chosen === option.kind}
              someoneChosen={run.chosen != null}
              choosing={choosing === option.kind}
              onChoose={() => onChoose(option.kind)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

/** Weather + assumptions, folded into one line. */
function Notes({ run }: { run: RunOut }) {
  const [open, setOpen] = useState(false);
  const count = run.assumptions.length + (run.weather_note ? 1 : 0);
  if (!count) return null;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white/70 px-3 py-1 text-xs font-medium text-muted backdrop-blur transition-colors hover:border-violet hover:text-violet-ink"
      >
        <CloudSun size={14} className="text-orchid-ink" aria-hidden />
        Weather and assumptions ({count})
        <ChevronDown size={13} className={`transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <ul className="animate-fade-up mt-2 space-y-1.5 rounded-2xl border border-line bg-white/70 p-3 text-sm text-muted backdrop-blur">
          {run.weather_note && (
            <li className="flex items-start gap-2">
              <CloudSun size={15} className="mt-0.5 shrink-0 text-orchid-ink" aria-hidden />
              <span>{run.weather_note}</span>
            </li>
          )}
          {run.assumptions.map((a) => (
            <li key={a} className="flex items-start gap-2">
              <Info size={15} className="mt-0.5 shrink-0 text-faint" aria-hidden />
              <span>{a}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusIcon({ option }: { option: PlanOptionOut }) {
  const { status } = option.validation;
  if (status === "pass")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-medium text-good" title="Fits your budget and time">
        <CircleCheck size={12} aria-hidden /> Fits
      </span>
    );
  if (status === "warn")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-butter px-2 py-0.5 text-[11px] font-medium text-warn" title="Fits, with a note to read">
        <TriangleAlert size={12} aria-hidden /> Fits*
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-pink-soft px-2 py-0.5 text-[11px] font-medium text-bad" title="Doesn't fully fit">
      <CircleX size={12} aria-hidden /> Partial
    </span>
  );
}

function PlanCard({
  option,
  chosen,
  someoneChosen,
  choosing,
  onChoose,
}: {
  option: PlanOptionOut;
  chosen: boolean;
  someoneChosen: boolean;
  choosing: boolean;
  onChoose: () => void;
}) {
  const [open, setOpen] = useState(false);
  const featured = option.kind === "recommended";
  const style = KIND_STYLE[option.kind];
  const Icon = style.icon;
  const { totals } = option;

  return (
    <article
      className={[
        "relative flex flex-col gap-3.5 rounded-3xl bg-white/85 p-4 backdrop-blur transition-all sm:p-5",
        featured
          ? "ring-brand order-first shadow-lift [--ring-width:2px] @3xl:order-none @3xl:-translate-y-3"
          : "border border-line shadow-card",
        chosen ? "outline-2 outline-offset-2 outline-good" : "",
        someoneChosen && !chosen ? "opacity-70" : "",
      ].join(" ")}
      aria-label={`${KIND_LABELS[option.kind]}: ${option.title}`}
    >
      {featured && (
        <span className="absolute -top-3 left-5 rounded-full bg-brand px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-white shadow-card">
          Best fit
        </span>
      )}

      <header className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${style.soft} ${style.text}`}>
            <Icon size={12} aria-hidden />
            {KIND_LABELS[option.kind]}
          </span>
          <StatusIcon option={option} />
        </div>
        <h3 className="text-[17px] font-semibold leading-snug tracking-tight text-ink">{option.title}</h3>
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm text-muted">
          <span className="text-base font-semibold tabular-nums text-ink">{rupees(totals.cost_inr)}</span>
          <span className="tabular-nums">of {rupees(totals.budget_inr)}</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{clockRange(totals.start, totals.end)}</span>
        </p>
      </header>

      {open ? <Details option={option} /> : <Stops items={option.items} dot={style.dot} />}

      <div className="mt-auto flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 rounded-full px-2.5 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-violet-soft hover:text-violet-ink"
        >
          {open ? "Less" : "Details"}
          <ChevronDown size={15} className={`transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
        </button>
        <button
          type="button"
          onClick={onChoose}
          disabled={chosen || choosing}
          className={[
            "ml-auto inline-flex items-center justify-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-semibold transition-all",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet",
            chosen
              ? "bg-good-soft text-good"
              : featured
                ? "bg-brand-deep text-white shadow-card hover:shadow-lift"
                : "border border-line-strong bg-white text-ink hover:border-violet hover:text-violet-ink",
          ].join(" ")}
        >
          {choosing ? <LoaderCircle size={15} className="animate-spin" aria-hidden /> : chosen ? <Check size={15} aria-hidden /> : null}
          {chosen ? "Picked" : "Pick this"}
        </button>
      </div>
    </article>
  );
}

/** Collapsed view: just the stops and their times. */
function Stops({ items, dot }: { items: PlanItemOut[]; dot: string }) {
  return (
    <ol className="space-y-2">
      {items.map((item) => {
        const KindIcon = item.kind === "restaurant" ? UtensilsCrossed : item.kind === "event" ? Ticket : item.indoor ? House : Trees;
        return (
          <li key={`${item.ref_id}-${item.start}`} className="flex items-center gap-2.5 text-sm">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
            <span className="w-16 shrink-0 text-xs font-medium tabular-nums text-muted">{clock(item.start)}</span>
            <KindIcon size={14} className="shrink-0 text-faint" aria-hidden />
            <span className="min-w-0 truncate text-ink">{item.name}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Expanded view: pitch, cost and time, the full timeline with travel, and trade-offs. */
function Details({ option }: { option: PlanOptionOut }) {
  const { totals } = option;
  const usedMin = totals.activity_min + totals.travel_min;
  return (
    <div className="animate-fade-up space-y-4">
      {option.pitch && <p className="text-sm leading-snug text-muted">{option.pitch}</p>}

      <div className="space-y-2.5">
        <Meter label="Cost" value={totals.cost_inr} limit={totals.budget_inr} detail={`${rupees(totals.cost_inr)} of ${rupees(totals.budget_inr)}`} />
        <Meter label="Time" value={usedMin} limit={totals.available_min} detail={`${minutes(usedMin)} of ${minutes(totals.available_min)}`} />
        <p className="text-[11px] text-faint">
          {rupees(totals.spend_inr)} tickets &amp; food + {rupees(totals.travel_inr)} travel · {minutes(totals.travel_min)} on the road
        </p>
      </div>

      <ol className="ml-2 space-y-3 border-l border-line-strong pl-4">
        {option.items.map((item) => (
          <FragmentRows key={`${item.ref_id}-${item.start}`} item={item} />
        ))}
        {option.leg_home && <LegRow leg={option.leg_home} home end={totals.end} />}
      </ol>

      {option.tradeoffs.length > 0 && (
        <div className="rounded-2xl bg-butter/80 px-3 py-2.5">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-ink">
            <Scale size={13} className="text-warn" aria-hidden /> Trade-offs
          </p>
          <ul className="list-disc space-y-1 pl-4 text-sm leading-snug text-muted marker:text-faint">
            {option.tradeoffs.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      {(option.validation.violations.length > 0 || option.validation.warnings.length > 0) && (
        <ul className="space-y-1 text-xs">
          {option.validation.violations.map((v) => (
            <li key={v} className="flex items-start gap-1.5 text-bad">
              <CircleX size={13} className="mt-px shrink-0" aria-hidden /> {v}
            </li>
          ))}
          {option.validation.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5 text-warn">
              <TriangleAlert size={13} className="mt-px shrink-0" aria-hidden /> {w}
            </li>
          ))}
        </ul>
      )}

      {option.source === "fallback" && <p className="text-[11px] text-faint">Built by the rule-based planner.</p>}
    </div>
  );
}

function Meter({ label, value, limit, detail }: { label: string; value: number; limit: number; detail: string }) {
  const pct = limit > 0 ? (value / limit) * 100 : 0;
  const fill = pct <= 100 ? "bg-brand" : pct <= 110 ? "bg-pink" : "bg-pink-ink";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums text-ink">{detail}</span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-violet-soft"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={value}
      >
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${Math.min(100, Math.max(3, pct))}%` }} />
      </div>
    </div>
  );
}

function LegRow({ leg, home = false, end }: { leg: Leg; home?: boolean; end?: string }) {
  const Icon = MODE_ICON[leg.mode] ?? Car;
  return (
    <li className="relative flex items-center gap-1.5 text-xs text-muted">
      <span className="absolute -left-[21px] h-2.5 w-2.5 rounded-full border border-line-strong bg-white" />
      {home ? <House size={13} className="shrink-0" aria-hidden /> : <Icon size={13} className="shrink-0" aria-hidden />}
      <span className="min-w-0">
        {home ? (
          <>
            {MODE_LABEL[leg.mode]} back · {leg.minutes} min · {leg.fare_inr ? rupees(leg.fare_inr) : "free"}
            {end && <span className="font-medium text-ink"> · home by {clock(end)}</span>}
          </>
        ) : (
          <>
            {MODE_LABEL[leg.mode]} · {leg.km.toFixed(1)} km · {leg.minutes} min · {leg.fare_inr ? rupees(leg.fare_inr) : "free"}
          </>
        )}
      </span>
    </li>
  );
}

function Chip({ icon: Icon, children, tone = "plain" }: { icon: LucideIcon; children: string; tone?: "plain" | "good" | "warn" }) {
  const cls = tone === "good" ? "bg-good-soft text-good" : tone === "warn" ? "bg-butter text-warn" : "bg-violet-soft/70 text-muted";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] ${cls}`}>
      <Icon size={11} aria-hidden />
      {children}
    </span>
  );
}

function ItemRow({ item }: { item: PlanItemOut }) {
  const cost =
    item.cost_inr === 0
      ? "Free"
      : item.kind === "restaurant"
        ? `${rupees(item.cost_inr)} for one`
        : `${rupees(item.cost_inr)}${item.tier ? ` · ${item.tier}` : ""}`;
  return (
    <li className="relative">
      <span className="absolute -left-[22.5px] top-1 h-3.5 w-3.5 rounded-full border-2 border-white bg-brand shadow-card" />
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-semibold tabular-nums text-violet-ink">{clockRange(item.start, item.end)}</span>
        <span className="shrink-0 text-xs tabular-nums text-muted">{cost}</span>
      </div>
      <p className="mt-0.5 font-medium leading-snug text-ink">{item.name}</p>
      <p className="text-xs capitalize text-muted">
        {item.label.replace(/_/g, " ")} · {item.area}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        <Chip icon={Users} tone={item.crowd === "high" ? "warn" : "plain"}>
          {CROWD_LABEL[item.crowd]}
        </Chip>
        <Chip icon={item.indoor ? House : Trees}>{item.indoor ? "Indoor" : "Outdoor"}</Chip>
        {item.veg && item.veg !== "non_veg" && (
          <Chip icon={Leaf} tone="good">
            {VEG_LABEL[item.veg]}
          </Chip>
        )}
      </div>
      <p className="mt-1.5 text-sm leading-snug text-ink">
        <span className="font-semibold text-orchid-ink">Why: </span>
        {item.why_it_fits}
      </p>
      {item.blurb && <p className="mt-1 line-clamp-2 text-xs text-muted">{item.blurb}</p>}
    </li>
  );
}

function FragmentRows({ item }: { item: PlanItemOut }) {
  return (
    <>
      {item.leg_before && <LegRow leg={item.leg_before} />}
      <ItemRow item={item} />
    </>
  );
}
