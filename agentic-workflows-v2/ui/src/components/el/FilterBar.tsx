import { useEffect, useRef, type ComponentProps } from "react";
import { ChevronDown, Search } from "lucide-react";

import { cn } from "@/lib/utils";

import {
  hasCommandModifier,
  isInOverlay,
  isTypingTarget,
} from "./keyboardGuards";

/**
 * The filter bar: one search field, at most two selects and a status segment,
 * directly above the table it filters. All parts are controlled; the page owns
 * the state (and reflects it in the URL). Phones (760px and below) give every
 * control the full width.
 */
export function FilterBar({ className, ...props }: Readonly<ComponentProps<"div">>) {
  return (
    <div
      data-slot="filter-bar"
      className={cn("flex flex-wrap items-center gap-2", className)}
      {...props}
    />
  );
}

export interface FilterOption<Value extends string = string> {
  value: Value;
  /** Sentence case. */
  label: string;
}

export interface FilterSearchProps
  extends Omit<
    ComponentProps<"input">,
    "value" | "onChange" | "type" | "aria-label" | "ref"
  > {
  value: string;
  onChange: (value: string) => void;
  /** Accessible name, e.g. "Search runs by id or workflow". */
  "aria-label": string;
  /** Key that focuses the field from anywhere outside a text input. `false` turns it off. */
  focusShortcut?: string | false;
}

/** Search field with a leading icon. `/` focuses it unless `focusShortcut` says otherwise. */
export function FilterSearch({
  value,
  onChange,
  focusShortcut = "/",
  className,
  ...inputProps
}: Readonly<FilterSearchProps>) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focusShortcut === false) return;
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key !== focusShortcut || event.defaultPrevented) return;
      if (hasCommandModifier(event)) return;
      const focused = document.activeElement;
      if (isTypingTarget(focused) || isInOverlay(focused)) return;
      event.preventDefault(); // "/" would otherwise open the browser's quick find
      inputRef.current?.focus();
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [focusShortcut]);

  return (
    <label
      className={cn(
        "flex min-h-10 min-w-[260px] items-center gap-2 rounded-md border border-el-control-border bg-el-raised px-3 text-el-muted focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-el-focus max-[760px]:min-w-0 max-[760px]:flex-[1_1_100%]",
        className,
      )}
    >
      <Search aria-hidden="true" strokeWidth={1.5} className="size-4 flex-none" />
      <input
        {...inputProps}
        ref={inputRef}
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-keyshortcuts={focusShortcut === false ? undefined : focusShortcut}
        autoComplete="off"
        spellCheck={false}
        className="min-w-0 flex-1 bg-transparent text-sm text-el-ink outline-hidden placeholder:text-el-muted [&::-webkit-search-cancel-button]:appearance-none"
      />
    </label>
  );
}

export interface FilterSelectProps<Value extends string> {
  value: Value;
  onChange: (value: Value) => void;
  options: readonly FilterOption<Value>[];
  /** Accessible name, e.g. "Workflow". */
  "aria-label": string;
  className?: string;
}

/** A native select styled as a control: 40px tall, 4px radius, chevron at the end. */
export function FilterSelect<Value extends string>({
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
  className,
}: Readonly<FilterSelectProps<Value>>) {
  return (
    <span className={cn("relative inline-flex max-[760px]:flex-auto", className)}>
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => {
          const match = options.find((o) => o.value === event.target.value);
          if (match) onChange(match.value);
        }}
        className="focus-ring h-10 w-full appearance-none rounded-md border border-el-control-border bg-el-raised pr-8 pl-3 text-sm text-el-ink"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden="true"
        strokeWidth={1.5}
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-el-muted"
      />
    </span>
  );
}

export interface FilterSegmentsProps<Value extends string> {
  value: Value;
  onChange: (value: Value) => void;
  options: readonly FilterOption<Value>[];
  /** Accessible name of the group, e.g. "Status". */
  "aria-label": string;
  className?: string;
}

/** Segmented buttons for the fixed status words; the current one is raised. */
export function FilterSegments<Value extends string>({
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
  className,
}: Readonly<FilterSegmentsProps<Value>>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex gap-0.5 rounded-md bg-el-subtle p-[3px] max-[760px]:order-3 max-[760px]:flex max-[760px]:basis-full",
        className,
      )}
    >
      {options.map((option) => {
        const pressed = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={pressed}
            onClick={() => onChange(option.value)}
            className={cn(
              "focus-ring flex h-[34px] items-center justify-center rounded-sm px-3 text-[13px] leading-none font-medium transition-colors duration-150 max-[760px]:flex-1",
              pressed
                ? "bg-el-raised text-el-ink shadow-[0_0_0_1px_rgb(var(--el-divider))]"
                : "text-el-muted hover:text-el-ink",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
