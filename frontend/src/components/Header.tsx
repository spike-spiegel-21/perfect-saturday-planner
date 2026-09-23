import { Plus, Sun } from "lucide-react";

interface Props {
  landing: boolean;
  offline: boolean;
  onNewPlan: () => void;
}

export function Logo({ size = 32 }: { size?: number }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-xl bg-brand text-accent-ink shadow-card"
      style={{ width: size, height: size }}
      aria-hidden
    >
      <Sun size={Math.round(size * 0.56)} strokeWidth={2.4} />
    </span>
  );
}

export function Header({ landing, offline, onNewPlan }: Props) {
  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center gap-2 px-4 sm:px-5">
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <Logo />
        <p className="truncate text-[15px] font-semibold tracking-tight text-ink">Perfect Saturday</p>
        {offline && (
          <span
            className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn"
            title="No AI key is configured on the server, so plans come from the rule-based planner."
          >
            Offline mode
          </span>
        )}
      </div>
      {!landing && (
        <button
          type="button"
          onClick={onNewPlan}
          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/60 px-3 py-1.5 text-sm font-medium text-ink backdrop-blur transition-colors hover:border-accent hover:text-accent"
        >
          <Plus size={16} aria-hidden />
          New plan
        </button>
      )}
    </header>
  );
}
