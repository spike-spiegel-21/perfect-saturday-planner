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
  pills: Pill[];
  multi: boolean;
  placeholder: string;
  disabled: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  /** Changes whenever a new assistant turn arrives, to reset the draft. */
  turnKey: string;
}

export function Composer({ pills, multi, placeholder, disabled, busy, onSend, turnKey }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setText("");
  }, [turnKey]);

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

  return (
    <div className="border-t border-line bg-canvas/95 backdrop-blur supports-[backdrop-filter]:bg-canvas/80">
      <div className="mx-auto w-full max-w-3xl px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
        {pills.length > 0 && !disabled && (
          <div className="mb-2.5 flex flex-wrap gap-1.5 sm:gap-2" role="group" aria-label="Suggestions">
            {pills.map((pill) => {
              const on = hasPart(text, pill.value);
              return (
                <button
                  key={`${pill.label}-${pill.value}`}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(pill)}
                  className={[
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[13px] transition-colors sm:px-3 sm:py-1.5 sm:text-sm",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    on
                      ? "border-accent bg-accent text-accent-ink"
                      : "border-line bg-surface text-ink hover:border-accent hover:text-accent-strong",
                  ].join(" ")}
                >
                  {on ? (
                    <Check size={14} aria-hidden />
                  ) : pill.remembered ? (
                    <Brain size={14} className="text-accent" aria-label="remembered from last time" />
                  ) : null}
                  {pill.label}
                </button>
              );
            })}
          </div>
        )}

        <div
          className={[
            "flex items-end gap-2 rounded-2xl border bg-surface px-3 py-2 shadow-card transition-colors",
            disabled ? "border-line opacity-70" : "border-line focus-within:border-accent",
          ].join(" ")}
        >
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
            className="max-h-42 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 text-ink outline-none placeholder:text-faint disabled:cursor-not-allowed"
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled || busy || !text.trim()}
            aria-label="Send"
            className="mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink transition-opacity hover:bg-accent-strong disabled:opacity-35 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <ArrowUp size={18} strokeWidth={2.4} aria-hidden />
          </button>
        </div>
        <p className="mt-1.5 hidden text-center text-[11px] text-faint sm:block">
          Enter to send · Shift+Enter for a new line · Mock data, illustrative prices
        </p>
        <p className="mt-1.5 text-center text-[11px] text-faint sm:hidden">Mock data · illustrative prices</p>
      </div>
    </div>
  );
}
