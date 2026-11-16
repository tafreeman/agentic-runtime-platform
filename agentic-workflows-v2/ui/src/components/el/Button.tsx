import type { ComponentProps, MouseEvent, ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

import { Button as UiButton } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Evidence Ledger button variants over the shadcn Button.
 *
 * - primary: the view's one decisive action. Never two in a view; never orange
 *   or blue (orange is the brand signal, blue is selection).
 * - secondary: outlined in `control-border`.
 * - quiet: no outline until hover, for toolbars and tertiary actions.
 */
export type ElButtonVariant = "primary" | "secondary" | "quiet";
export type ElButtonSize = "default" | "sm" | "icon";

const VARIANT_CLASS: Readonly<Record<ElButtonVariant, string>> = {
  primary:
    "border-el-action bg-el-action text-el-action-ink hover:border-el-secondary hover:bg-el-secondary",
  secondary:
    "border-el-control-border bg-transparent text-el-ink hover:bg-el-hover",
  quiet: "border-transparent bg-transparent text-el-secondary hover:bg-el-hover",
};

// Which shadcn variant supplies the base, so the overrides above stay small.
const BASE_VARIANT = {
  primary: "default",
  secondary: "outline",
  quiet: "ghost",
} as const;

// 36px high with 16px side padding is the spec and is never compressed. The
// small size is the toolbar height, 32px; icon is a 36px square.
const SIZE_CLASS: Readonly<Record<ElButtonSize, string>> = {
  default: "h-9 px-4",
  sm: "h-8 px-3 text-[13px]",
  icon: "size-9 p-0",
};

const BASE_SIZE = { default: "default", sm: "sm", icon: "icon" } as const;

type UiButtonProps = ComponentProps<typeof UiButton>;

interface ElButtonCommon extends Omit<UiButtonProps, "variant" | "size" | "children"> {
  variant?: ElButtonVariant;
  /** Leading icon; a spinner replaces it while `loading`. */
  icon?: ReactNode;
  /** The label stays, a spinner replaces the icon, and clicks are ignored. */
  loading?: boolean;
  children?: ReactNode;
}

export type ElButtonProps =
  | (ElButtonCommon & { size?: "default" | "sm" })
  // An icon-only button has no text, so it must say what it does.
  | (ElButtonCommon & { size: "icon"; "aria-label": string });

/** A native button: forwards every prop (including `disabled`) to the shadcn one. */
export function Button(props: Readonly<ElButtonProps>) {
  const {
    variant = "secondary",
    size = "default",
    icon,
    loading = false,
    className,
    children,
    onClick,
    "aria-busy": ariaBusy,
    "aria-disabled": ariaDisabled,
    ...rest
  } = props;

  // Loading keeps the button focusable (focus must not vanish mid-action), so
  // it uses aria-disabled and swallows the click instead of `disabled`.
  function handleClick(event: MouseEvent<HTMLButtonElement>): void {
    if (loading) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  }

  const leading = loading ? (
    <LoaderCircle aria-hidden="true" className="motion-safe:animate-spin" />
  ) : (
    icon
  );

  return (
    <UiButton
      {...rest}
      variant={BASE_VARIANT[variant]}
      size={BASE_SIZE[size]}
      data-el-variant={variant}
      aria-busy={loading ? true : ariaBusy}
      aria-disabled={loading ? true : ariaDisabled}
      onClick={handleClick}
      className={cn(
        "font-medium [&_code]:font-mono [&_code]:text-[13px]",
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        loading && "cursor-progress",
        className,
      )}
    >
      {leading}
      {children}
    </UiButton>
  );
}
