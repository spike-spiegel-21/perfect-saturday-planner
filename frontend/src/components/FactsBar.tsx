import { BatteryMedium, Clock, Heart, MapPin, ShieldCheck, Wallet, type LucideIcon } from "lucide-react";
import { clock, FIELD_LABEL, hours, rupees } from "../format";
import type { Slots } from "../types";

interface Fact {
  field: string;
  icon: LucideIcon;
  value: string | null;
}

function facts(slots: Slots): Fact[] {
  const city = slots.city_name ?? slots.city;
  return [
    { field: "city", icon: MapPin, value: city ? (slots.start_area ? `${city} · ${slots.start_area}` : city) : null },
    { field: "budget", icon: Wallet, value: slots.budget_inr != null ? rupees(slots.budget_inr) : null },
    {
      field: "available_time",
      icon: Clock,
      value:
        slots.available_hours != null
          ? `${hours(slots.available_hours)}${slots.start_time ? ` from ${clock(slots.start_time)}` : ""}`
          : null,
    },
    { field: "mood", icon: BatteryMedium, value: slots.mood },
    { field: "interests", icon: Heart, value: slots.interests?.length ? slots.interests.join(", ") : null },
    {
      field: "constraints",
      icon: ShieldCheck,
      value: slots.constraints == null ? null : slots.constraints.length ? slots.constraints.join(", ") : "No constraints",
    },
  ];
}

/** "What I know so far": filled answers as chips, missing ones as dashed placeholders. */
export function FactsBar({ slots, asking }: { slots: Slots; asking: string | null }) {
  const list = facts(slots);
  if (list.every((f) => !f.value)) return null;

  return (
    <div className="sticky top-0 z-20 px-4 pb-1 pt-2">
      {/* A frosted band that fades out downwards, so messages soften as they scroll under the chips. */}
      <div
        className="pointer-events-none absolute inset-x-0 -bottom-5 top-0 bg-canvas/40 backdrop-blur-md [mask-image:linear-gradient(to_bottom,black_55%,transparent)]"
        aria-hidden
      />
      <ul
        className="relative mx-auto flex w-full max-w-5xl items-center gap-1.5 overflow-x-auto [scrollbar-width:none] sm:flex-wrap sm:overflow-visible"
        aria-label="What I know so far"
      >
        {list.map(({ field, icon: Icon, value }) => {
          const active = !value && asking === field;
          return (
            <li
              key={field}
              title={value ? `${FIELD_LABEL[field]}: ${value}` : `${FIELD_LABEL[field]}: not answered yet`}
              className={[
                "inline-flex max-w-[16rem] shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs backdrop-blur",
                value
                  ? "border-line bg-white/80 text-ink shadow-card"
                  : active
                    ? "border-dashed border-violet bg-white/60 text-violet-ink"
                    : "border-dashed border-line-strong bg-white/40 text-faint",
              ].join(" ")}
            >
              <Icon size={13} className={value ? "shrink-0 text-violet" : "shrink-0"} aria-hidden />
              <span className="truncate">{value ?? FIELD_LABEL[field]}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
