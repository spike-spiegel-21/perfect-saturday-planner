import { ArrowUp, Brain, Check } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Pill } from "../types";

// The textarea is the single source of truth: a pill counts as selected when its value
// appears as one of the comma-separated parts, so typing and clicking never drift apart.
const parts = (text: string) =>
  text
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();
const hasPart = (text: string, value: string) => parts(text).some((p) => same(p, value));
const removePart = (text: string, value: string) =>
  parts(text)
    .filter((p) => !same(p, value))
    .join(", ");
const addPart = (text: string, value: string) => {
  const base = text.trim().replace(/,\s*$/, "");
  return base ? `${base}, ${value}` : value;
};
const isNone = (value: string) => ["none", "no constraints", "nothing"].includes(value.trim().toLowerCase());

interface Props {
  variant: "hero" | "dock";
  pills: Pill[];
  multi: boolean;
  placeholder: string;
  disabled: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  /** Changes whenever a new assistant turn arrives, to reset the draft. */
  turnKey: string;
}

export function Composer({ variant, pills, multi, placeholder, disabled, busy, onSend, turnKey }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const hero = variant === "hero";

  useEffect(() => {
    setText("");
  }, [turnKey]);

  // Keep the cursor in the box: on the landing screen, and after every new question.
  useEffect(() => {
    if (!disabled) ref.current?.focus({ preventScroll: true });
  }, [turnKey, disabled]);

  // Grow with the content, up to ~6 lines.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [text]);

  const toggle = (pill: Pill) => {
    setText((prev) => {
      if (hasPart(prev, pill.value)) return removePart(prev, pill.value);
      let next = prev;
      if (!multi || isNone(pill.value)) {
        for (const other of pills) if (other.value !== pill.value) next = removePart(next, other.value);
      } else {
        for (const other of pills) if (isNone(other.value)) next = removePart(next, other.value);
      }
      return addPart(next, pill.value);
    });
    ref.current?.focus();
  };

  const submit = () => {
    const value = text.trim();
    if (!value || disabled || busy) return;
    onSend(value);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const showPills = pills.length > 0 && !disabled;

  return (
    <div>
      {/* The transition name sits on the glass card itself: an ancestor carrying it would become the
          backdrop root, and the blur would then have nothing behind it to blur. */}
      <div
        style={{ viewTransitionName: "composer" }}
        className="ring-brand glass rounded-[28px] border border-line shadow-float transition-[border-color] [--ring-opacity:0] focus-within:border-transparent focus-within:[--ring-opacity:1]"
      >
        {showPills && (
          <div
            className="flex gap-1.5 overflow-x-auto px-3 pt-3 [scrollbar-width:none] sm:flex-wrap sm:gap-2 sm:overflow-visible"
            role="group"
            aria-label="Suggestions"
          >
            {pills.map((pill) => {
              const on = hasPart(text, pill.value);
              return (
                <button
                  key={`${pill.label}-${pill.value}`}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(pill)}
                  className={[
                    "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-[13px] font-medium transition-all sm:py-1.5 sm:text-sm",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet",
                    on
                      ? "border-transparent bg-brand-deep text-white shadow-card"
                      : "border-line-strong bg-white/80 text-ink hover:-translate-y-px hover:border-violet hover:text-violet-ink",
                  ].join(" ")}
                >
                  {on ? (
                    <Check size={14} aria-hidden />
                  ) : pill.remembered ? (
                    <Brain size={14} className="text-orchid-ink" aria-label="remembered from last time" />
                  ) : null}
                  {pill.label}
                </button>
              );
            })}
          </div>
        )}

        <div className={`flex items-end gap-2 ${hero ? "px-4 py-3" : "px-3 py-2.5"} ${disabled ? "opacity-60" : ""}`}>
          <textarea
            ref={ref}
            rows={1}
            value={text}
            maxLength={1000}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Message"
            className={[
              "max-h-42 flex-1 resize-none bg-transparent leading-6 text-ink outline-none placeholder:text-faint disabled:cursor-not-allowed",
              hero ? "min-h-12 py-3 text-[17px]" : "min-h-10 py-2 text-[15px]",
            ].join(" ")}
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled || busy || !text.trim()}
            aria-label="Send"
            className={[
              "inline-flex shrink-0 items-center justify-center rounded-full bg-brand text-white shadow-card transition-[opacity,transform] hover:scale-105 disabled:scale-100 disabled:opacity-35",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet",
              hero ? "mb-1 h-11 w-11" : "mb-0.5 h-10 w-10",
            ].join(" ")}
          >
            <ArrowUp size={hero ? 20 : 18} strokeWidth={2.4} aria-hidden />
          </button>
        </div>
      </div>
      {hero && (
        <p className="mt-2 text-center text-[11px] text-faint">
          <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line · </span>Mock data · illustrative prices
        </p>
      )}
    </div>
  );
}
