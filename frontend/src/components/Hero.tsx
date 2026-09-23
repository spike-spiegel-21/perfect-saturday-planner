import { Brain } from "lucide-react";
import { Logo } from "./Header";

/** The landing view: one open question, no form. The composer sits right under it. */
export function Hero({ memoryHint }: { memoryHint: string | null }) {
  return (
    <div className="mx-auto max-w-2xl text-center" style={{ viewTransitionName: "hero" }}>
      <div className="mb-6 flex justify-center">
        <Logo size={56} />
      </div>
      {memoryHint && (
        <p className="mx-auto mb-4 inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-white/70 px-3 py-1 text-xs text-muted backdrop-blur">
          <Brain size={13} className="shrink-0 text-orchid-ink" aria-hidden />
          <span className="truncate">Welcome back · {memoryHint}</span>
        </p>
      )}
      <h1 className="text-[34px] font-semibold leading-[1.1] tracking-tight text-ink sm:text-5xl">
        How should we plan your <span className="text-brand">Saturday</span>?
      </h1>
      <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted sm:text-lg">
        Tell me anything: where you are, your budget, how much time you have, how you&apos;re feeling.
      </p>
    </div>
  );
}
