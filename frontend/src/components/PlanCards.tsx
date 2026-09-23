import {
  Car,
  CarTaxiFront,
  Check,
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
  TrainFront,
  Trees,
  TriangleAlert,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";
import {
  clock,
  clockRange,
  CROWD_LABEL,
  fallbackReason,
  minutes,
  MODE_LABEL,
  rupees,
  VEG_LABEL,
} from "../format";
import { KIND_LABELS, KIND_ORDER, type Leg, type OptionKind, type PlanItemOut, type PlanOptionOut, type RunOut } from "../types";

const KIND_ICON: Record<OptionKind, LucideIcon> = {
  time_saver: Zap,
  recommended: Sparkles,
  value_for_money: PiggyBank,
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
        <div className="flex items-start gap-2.5 rounded-xl border border-warn/30 bg-warn-soft px-3.5 py-2.5 text-sm text-ink">
          <TriangleAlert size={17} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          <p>
            <span className="font-medium">Showing a rule-based plan</span>{" "}
            <span className="text-muted">
              because {fallbackReason(run.fallback_reason)}. It uses the same data and the same budget and time checks.
            </span>
          </p>
        </div>
      )}

      {(run.assumptions.length > 0 || run.weather_note) && (
        <div className="flex flex-col gap-1.5 text-sm text-muted">
          {run.weather_note && (
            <p className="flex items-start gap-2">
              <CloudSun size={16} className="mt-0.5 shrink-0 text-info" aria-hidden />
              <span>{run.weather_note}</span>
            </p>
          )}
          {run.assumptions.map((a) => (
            <p key={a} className="flex items-start gap-2">
              <Info size={16} className="mt-0.5 shrink-0 text-faint" aria-hidden />
              <span>{a}</span>
            </p>
          ))}
        </div>
      )}

      <div className="@container">
        <div className="grid grid-cols-1 gap-4 pt-1 @3xl:grid-cols-3 @3xl:items-start @3xl:pt-3">
          {options.map((option) => (
            <PlanCard
              key={option.kind}
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

function StatusChip({ option }: { option: PlanOptionOut }) {
  const { status } = option.validation;
  if (status === "pass")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-medium text-good">
        <CircleCheck size={12} aria-hidden /> Fits budget &amp; time
      </span>
    );
  if (status === "warn")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">
        <TriangleAlert size={12} aria-hidden /> Fits, with notes
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-bad-soft px-2 py-0.5 text-[11px] font-medium text-bad">
      <CircleX size={12} aria-hidden /> Doesn&apos;t fully fit
    </span>
  );
}

function Meter({ label, value, limit, detail }: { label: string; value: number; limit: number; detail: string }) {
  const pct = limit > 0 ? (value / limit) * 100 : 0;
  const tone = pct <= 100 ? "bg-good" : pct <= 110 ? "bg-warn" : "bg-bad";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums text-ink">{detail}</span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={value}
      >
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, Math.max(3, pct))}%` }} />
      </div>
    </div>
  );
}

function LegRow({ leg, home = false, end }: { leg: Leg; home?: boolean; end?: string }) {
  const Icon = MODE_ICON[leg.mode] ?? Car;
  return (
    <li className="relative flex items-center gap-1.5 text-xs text-muted">
      <span className="absolute -left-[21px] flex h-3 w-3 items-center justify-center rounded-full border border-line-strong bg-surface" />
      {home ? <House size={13} className="shrink-0" aria-hidden /> : <Icon size={13} className="shrink-0" aria-hidden />}
      <span className="min-w-0">
        {home ? (
          <>
            {MODE_LABEL[leg.mode]} home · {leg.minutes} min · {leg.fare_inr ? rupees(leg.fare_inr) : "free"}
            {end && <span className="font-medium text-ink"> · back by {clock(end)}</span>}
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
  const cls =
    tone === "good" ? "bg-good-soft text-good" : tone === "warn" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted";
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
      <span className="absolute -left-[22px] top-1 h-3.5 w-3.5 rounded-full border-2 border-surface bg-accent ring-1 ring-accent/40" />
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium tabular-nums text-accent-strong">{clockRange(item.start, item.end)}</span>
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
        <span className="font-medium text-accent-strong">Why: </span>
        {item.why_it_fits}
      </p>
      {item.blurb && <p className="mt-1 line-clamp-2 text-xs text-muted">{item.blurb}</p>}
    </li>
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
  const featured = option.kind === "recommended";
  const Icon = KIND_ICON[option.kind];
  const { totals } = option;
  const usedMin = totals.activity_min + totals.travel_min;

  return (
    <article
      className={[
        "relative flex flex-col gap-4 rounded-2xl border bg-surface p-4 transition-all",
        featured
          ? "order-first border-accent shadow-lift ring-1 ring-accent/25 @3xl:order-none @3xl:-translate-y-3"
          : "border-line shadow-card",
        chosen ? "ring-2 ring-good" : "",
        someoneChosen && !chosen ? "opacity-75" : "",
      ].join(" ")}
      aria-label={`${KIND_LABELS[option.kind]}: ${option.title}`}
    >
      {featured && (
        <span className="absolute -top-2.5 left-4 rounded-full bg-accent px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-accent-ink shadow-card">
          Best fit
        </span>
      )}

      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
            <Icon size={14} className="text-accent" aria-hidden />
            {KIND_LABELS[option.kind]}
          </span>
          <StatusChip option={option} />
        </div>
        <h3 className="text-lg font-semibold leading-snug text-ink">{option.title}</h3>
        <p className="text-sm leading-snug text-muted">{option.pitch}</p>
        {option.source === "fallback" && (
          <span className="inline-flex rounded-md bg-info-soft px-1.5 py-0.5 text-[11px] font-medium text-info">
            Rule-based fallback
          </span>
        )}
      </header>

      <div className="space-y-2.5">
        <Meter
          label="Cost"
          value={totals.cost_inr}
          limit={totals.budget_inr}
          detail={`${rupees(totals.cost_inr)} of ${rupees(totals.budget_inr)}`}
        />
        <Meter
          label="Time"
          value={usedMin}
          limit={totals.available_min}
          detail={`${minutes(usedMin)} of ${minutes(totals.available_min)}`}
        />
        <p className="text-[11px] text-faint">
          {rupees(totals.spend_inr)} tickets &amp; food + {rupees(totals.travel_inr)} travel · {minutes(totals.travel_min)} on the
          road
        </p>
      </div>

      <ol className="ml-2.5 space-y-3 border-l border-line pl-4">
        {option.items.map((item) => (
          <FragmentRows key={`${item.ref_id}-${item.start}`} item={item} />
        ))}
        {option.leg_home && <LegRow leg={option.leg_home} home end={totals.end} />}
      </ol>

      {option.tradeoffs.length > 0 && (
        <div className="rounded-xl bg-surface-2 px-3 py-2.5">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-ink">
            <Scale size={13} className="text-accent" aria-hidden /> Trade-offs
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

      <button
        type="button"
        onClick={onChoose}
        disabled={chosen || choosing}
        className={[
          "mt-auto inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          chosen
            ? "bg-good-soft text-good"
            : featured
              ? "bg-accent text-accent-ink hover:bg-accent-strong"
              : "border border-line text-ink hover:border-accent hover:text-accent-strong",
        ].join(" ")}
      >
        {choosing ? (
          <LoaderCircle size={15} className="animate-spin" aria-hidden />
        ) : chosen ? (
          <Check size={15} aria-hidden />
        ) : null}
        {chosen ? "Picked — saved for next time" : "Pick this plan"}
      </button>
    </article>
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
